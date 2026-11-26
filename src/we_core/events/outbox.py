"""Publisher da transactional outbox: SELECT … FOR UPDATE SKIP LOCKED, retry com backoff exponencial, DLQ."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from we_core.common import utcnow
from we_core.db import Database
from we_core.events.bus import EventBus
from we_core.events.store import envelope
from we_core.observability import metrics

log = logging.getLogger("we.outbox")
MAX_ATTEMPTS = 8


@dataclass
class PublishStats:
    published: int = 0
    duplicates: int = 0
    retried: int = 0
    dead: int = 0


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(2**attempts, 300))


PUBLISHER_LEASE = 727002


async def publish_batch(
    db: Database,
    bus: EventBus,
    batch_size: int = 100,
    tenant_id: UUID | None = None,
    use_lease: bool = True,
) -> PublishStats:
    """Corre com o role we_worker (política worker_all na outbox, leitura de eventos de todos os tenants).

    Lease de publicador único (advisory lock transacional): com várias réplicas do worker só uma publica
    em cada ciclo, preservando a ordem por tenant/agregado. As restantes ficam em espera ativa (hot standby).
    """
    stats = PublishStats()
    with db.pool.connection() as conn, conn.transaction():
        if use_lease:
            lease = conn.execute("SELECT pg_try_advisory_xact_lock(%s) AS ok", (PUBLISHER_LEASE,)).fetchone()
            if not lease or not lease["ok"]:
                return stats
        rows = conn.execute(
            """SELECT o.event_id, o.subject, o.attempts, e.*
               FROM event_store.outbox o JOIN event_store.events e
                 ON e.tenant_id = o.tenant_id AND e.event_id = o.event_id
               WHERE o.status = 'pending' AND o.next_attempt_at <= now()
                 AND (%s::uuid IS NULL OR o.tenant_id = %s::uuid)
               ORDER BY e.tenant_id, e.chain_seq
               LIMIT %s FOR UPDATE OF o SKIP LOCKED""",
            (tenant_id, tenant_id, batch_size),
        ).fetchall()
        for row in rows:
            try:
                fresh = await bus.publish(row["subject"], envelope(row), str(row["event_id"]))
                conn.execute(
                    "UPDATE event_store.outbox SET status='published', published_at=now(), attempts=attempts+1, "
                    "last_error=NULL WHERE event_id=%s",
                    (row["event_id"],),
                )
                stats.published += 1
                if not fresh:
                    stats.duplicates += 1
                metrics.outbox_published.inc()
            except Exception as exc:  # noqa: BLE001 - qualquer falha do broker → retry/DLQ
                attempts = int(row["attempts"]) + 1
                dead = attempts >= MAX_ATTEMPTS
                conn.execute(
                    "UPDATE event_store.outbox SET status=%s, attempts=%s, next_attempt_at=%s, last_error=%s "
                    "WHERE event_id=%s",
                    ("dead" if dead else "pending", attempts, utcnow() + backoff(attempts),
                     f"{type(exc).__name__}: {str(exc)[:300]}", row["event_id"]),
                )  # fmt: skip
                if dead:
                    stats.dead += 1
                    metrics.outbox_dead.inc()
                    log.error("evento %s movido para DLQ após %s tentativas", row["event_id"], attempts)
                else:
                    stats.retried += 1
                    metrics.outbox_retries.inc()
                # mantém a ordem por tenant: não publica eventos posteriores do mesmo tenant neste lote
                break
    return stats
