"""Projeções reconstruíveis a partir do Event Store.

`entity_summary`: atividade por entidade. Consumidor idempotente (processed_events) com checkpoint por
tenant. O replay apaga a projeção do tenant e reaplica os eventos por chain_seq — resultado determinístico
(digest comparável antes/depois).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from we_core.common import canonical_json, sha256_hex
from we_core.db import Conn

PROJECTION = "entity_summary"
ENTITY_EVENTS = {"kernel.entity_created", "kernel.entity_updated", "kernel.entity_role_assigned",
                 "kernel.relation_created"}  # fmt: skip


def apply(conn: Conn, event: dict[str, Any]) -> bool:
    """Aplica um evento (envelope ou linha) à projeção. Devolve False se já tinha sido processado."""
    tenant_id, event_id = event["tenant_id"], event["event_id"]
    inserted = conn.execute(
        "INSERT INTO projection.processed_events (tenant_id, projection_name, event_id) VALUES (%s,%s,%s) "
        "ON CONFLICT DO NOTHING RETURNING event_id",
        (tenant_id, PROJECTION, event_id),
    ).fetchone()
    if not inserted:
        return False
    if event["event_type"] in ENTITY_EVENTS and event["aggregate_type"] == "entity":
        p = event["payload"]
        conn.execute(
            """INSERT INTO projection.entity_summary (tenant_id, entity_id, entity_type, event_count,
                 last_event_type, last_aggregate_version, last_chain_seq, last_event_at)
               VALUES (%s,%s,%s,1,%s,%s,%s,%s)
               ON CONFLICT (tenant_id, entity_id) DO UPDATE SET
                 event_count = projection.entity_summary.event_count + 1,
                 entity_type = coalesce(EXCLUDED.entity_type, projection.entity_summary.entity_type),
                 last_event_type = EXCLUDED.last_event_type,
                 last_aggregate_version = greatest(projection.entity_summary.last_aggregate_version,
                                                   EXCLUDED.last_aggregate_version),
                 last_chain_seq = greatest(projection.entity_summary.last_chain_seq, EXCLUDED.last_chain_seq),
                 last_event_at = greatest(projection.entity_summary.last_event_at, EXCLUDED.last_event_at)""",
            (tenant_id, event["aggregate_id"], p.get("entity_type"), event["event_type"],
             event["aggregate_version"], event["chain_seq"], event["occurred_at"]),
        )  # fmt: skip
    conn.execute(
        """INSERT INTO projection.checkpoints (tenant_id, projection_name, last_chain_seq) VALUES (%s,%s,%s)
           ON CONFLICT (tenant_id, projection_name) DO UPDATE
           SET last_chain_seq = greatest(projection.checkpoints.last_chain_seq, EXCLUDED.last_chain_seq),
               updated_at = now()""",
        (tenant_id, PROJECTION, event["chain_seq"]),
    )
    return True


def digest(conn: Conn, tenant_id: UUID) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT entity_id, entity_type, event_count, last_event_type, last_aggregate_version, last_chain_seq "
        "FROM projection.entity_summary WHERE tenant_id = %s ORDER BY entity_id",
        (tenant_id,),
    ).fetchall()
    return {"rows": len(rows), "sha256": sha256_hex(canonical_json([dict(r) for r in rows]))}


def _rebuild(conn: Conn, tenant_id: UUID) -> int:
    conn.execute("DELETE FROM projection.entity_summary WHERE tenant_id = %s", (tenant_id,))
    conn.execute("DELETE FROM projection.processed_events WHERE tenant_id = %s AND projection_name = %s",
                 (tenant_id, PROJECTION))  # fmt: skip
    conn.execute("DELETE FROM projection.checkpoints WHERE tenant_id = %s AND projection_name = %s",
                 (tenant_id, PROJECTION))  # fmt: skip
    count = 0
    with conn.cursor(name="projection_replay") as cur:
        cur.itersize = 1000
        cur.execute("SELECT * FROM event_store.events WHERE tenant_id = %s ORDER BY chain_seq", (tenant_id,))
        for ev in cur:
            apply(conn, ev)
            count += 1
    return count


def replay(conn: Conn, tenant_id: UUID) -> dict[str, Any]:
    """Reconstrói duas vezes e compara digests: prova de determinismo do replay."""
    before = digest(conn, tenant_id)
    count = _rebuild(conn, tenant_id)
    first = digest(conn, tenant_id)
    _rebuild(conn, tenant_id)
    after = digest(conn, tenant_id)
    return {
        "projection": PROJECTION,
        "events_replayed": count,
        "before": before,
        "after": after,
        "deterministic": first == after,
        "matches_live": before == after,
    }


def lag(conn: Conn, tenant_id: UUID) -> dict[str, int]:
    head = conn.execute(
        "SELECT coalesce(max(chain_seq),0) AS s FROM event_store.events WHERE tenant_id = %s", (tenant_id,)
    ).fetchone()
    cp = conn.execute(
        "SELECT last_chain_seq FROM projection.checkpoints WHERE tenant_id = %s AND projection_name = %s",
        (tenant_id, PROJECTION),
    ).fetchone()
    h = int(head["s"]) if head else 0
    c = int(cp["last_chain_seq"]) if cp else 0
    return {"head_seq": h, "checkpoint_seq": c, "lag": max(h - c, 0)}
