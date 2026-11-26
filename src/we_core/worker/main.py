"""Worker: publica a outbox no EventBus e alimenta projeções a partir do bus (consumidor idempotente).

Expõe /healthz e /metrics (porta 9101).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from we_core.config import get_settings
from we_core.db import Database
from we_core.events import outbox, projections
from we_core.events.bus import EventBus, NatsJetStreamBus
from we_core.observability import metrics, setup_logging, setup_tracing

log = logging.getLogger("we.worker")
STATE: dict[str, Any] = {"healthy": False}


class _Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/metrics":
            body, ctype, code = generate_latest(), CONTENT_TYPE_LATEST, 200
        elif self.path == "/healthz":
            code = 200 if STATE["healthy"] else 503
            body, ctype = (
                (b'{"status":"ok"}' if code == 200 else b'{"status":"degraded"}'),
                "application/json",
            )
        else:
            body, ctype, code = b"", "text/plain", 404
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        return None


def make_projector(db: Database) -> Any:
    async def handle(env: dict[str, Any]) -> None:
        from uuid import UUID

        def _apply() -> bool:
            with db.tenant_tx(UUID(env["tenant_id"])) as conn:
                return projections.apply(conn, env)

        applied = await asyncio.to_thread(_apply)
        (metrics.consumer_processed if applied else metrics.consumer_duplicates).labels(
            projections.PROJECTION
        ).inc()

    return handle


def _refresh_gauges(db: Database) -> None:
    with db.pool.connection() as conn:
        row = conn.execute(
            """SELECT count(*) FILTER (WHERE status='pending') AS pending,
                      count(*) FILTER (WHERE status='dead') AS dead,
                      coalesce(extract(epoch FROM now() - min(created_at) FILTER (WHERE status='pending')),0) AS lag
               FROM event_store.outbox"""
        ).fetchone()
        pending = conn.execute("SELECT governance.pending_decisions_count() AS n").fetchone()
    if pending:
        metrics.decisions_pending.set(pending["n"])
    if row:
        metrics.outbox_pending.set(row["pending"])
        metrics.outbox_dlq.set(row["dead"])
        metrics.outbox_lag_seconds.set(float(row["lag"]))


async def run(stop: asyncio.Event, bus: EventBus | None = None, interval: float = 0.5) -> None:
    s = get_settings()
    db = Database(s.dsn("worker"), 1, 4)
    db.open()
    bus = bus or NatsJetStreamBus(s.nats_url, s.nats_stream)
    await bus.connect()
    await bus.subscribe("projection-entity-summary", make_projector(db))
    STATE["healthy"] = True
    log.info("worker ativo")
    tick = 0
    try:
        while not stop.is_set():
            try:
                stats = await outbox.publish_batch(db, bus)
                if stats.published or stats.retried or stats.dead:
                    log.info(
                        "outbox: publicados=%s retries=%s dlq=%s", stats.published, stats.retried, stats.dead
                    )
                if tick % 10 == 0:
                    await asyncio.to_thread(_refresh_gauges, db)
                STATE["healthy"] = await bus.healthy()
            except Exception:
                STATE["healthy"] = False
                log.exception("falha no ciclo do worker")
            tick += 1
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=interval)
    finally:
        await bus.close()
        db.close()


def main() -> None:
    s = get_settings()
    setup_logging("we-worker", s.log_level)
    setup_tracing("we-worker", s.otel_exporter_otlp_endpoint)
    server = ThreadingHTTPServer(("0.0.0.0", 9101), _Health)  # noqa: S104 - dentro do contentor
    Thread(target=server.serve_forever, daemon=True).start()

    async def _main() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await run(stop)

    asyncio.run(_main())
