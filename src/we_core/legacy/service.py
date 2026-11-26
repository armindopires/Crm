"""Legacy Integration (anti-corruption layer): lotes de staging, snapshots raw, reconciliação e quarentena.

Nesta fase não há ligação a bases reais. Um lote de staging regista intenção, parâmetros e contagens;
a extração real exige autorização específica, cópia controlada e cadeia de custódia (runbook migração).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from we_core.audit import log as audit
from we_core.common import uuid7
from we_core.context import OpContext
from we_core.db import Conn
from we_core.errors import Conflict, NotFound, ValidationFailed
from we_core.events.store import EventDraft, append
from we_core.identity.authz import Resource, require

TRANSITIONS = {
    "created": {"staging", "failed"},
    "staging": {"validated", "failed"},
    "validated": {"reconciled", "failed", "rolled_back"},
    "reconciled": {"rolled_back"},
    "failed": {"rolled_back"},
    "rolled_back": set(),
}


def create_batch(conn: Conn, ctx: OpContext, *, source_system_code: str, batch_kind: str,
                 parameters: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    require(conn, ctx.principal, "import:write", Resource("import_batch"))
    if not conn.execute("SELECT 1 FROM legacy.source_systems WHERE source_system_code = %s",
                        (source_system_code,)).fetchone():  # fmt: skip
        raise ValidationFailed(f"Sistema de origem desconhecido: {source_system_code}")
    forbidden = {
        k for k in parameters if any(s in k.lower() for s in ("password", "pwd", "secret", "token", "dsn"))
    }
    if forbidden:
        raise ValidationFailed("Parâmetros de lote não podem conter credenciais; use referências de cofre.",
                               code="WE-LEG-SECRET")  # fmt: skip
    batch_id = uuid7()
    row = conn.execute(
        "INSERT INTO legacy.import_batches (batch_id, tenant_id, source_system_code, batch_kind, parameters, "
        "started_by) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (batch_id, ctx.tenant_id, source_system_code, batch_kind, Jsonb(parameters), ctx.principal.actor_id),
    ).fetchone()
    assert row is not None
    append(
        conn,
        ctx,
        EventDraft(
            event_type="legacy.import_batch_created",
            aggregate_type="import_batch",
            aggregate_id=batch_id,
            expected_version=0,
            payload={"source_system_code": source_system_code, "batch_kind": batch_kind},
        ),
    )
    audit.record(
        conn,
        ctx,
        action="import_batch.create",
        resource_type="import_batch",
        resource_id=batch_id,
        outcome="succeeded",
        details={"source_system_code": source_system_code},
    )
    return {**dict(row), "reconciliations": []}


def transition(conn: Conn, ctx: OpContext, batch_id: UUID, to_status: str,
               counts: dict[str, int] | None = None) -> dict[str, Any]:  # fmt: skip
    row = conn.execute(
        "SELECT * FROM legacy.import_batches WHERE batch_id = %s FOR UPDATE", (batch_id,)
    ).fetchone()
    if not row:
        raise NotFound("Lote não encontrado.")
    if to_status not in TRANSITIONS[row["status"]]:
        raise Conflict(f"Transição de lote {row['status']} → {to_status} não permitida.", code="WE-LEG-STATE")
    new_counts = {**row["counts"], **(counts or {})}
    updated = conn.execute(
        "UPDATE legacy.import_batches SET status=%s, counts=%s, finished_at = CASE WHEN %s IN "
        "('reconciled','failed','rolled_back') THEN now() END WHERE batch_id=%s RETURNING *",
        (to_status, Jsonb(new_counts), to_status, batch_id),
    ).fetchone()
    assert updated is not None
    append(conn, ctx, EventDraft(event_type="legacy.import_batch_status_changed", aggregate_type="import_batch",
                                 aggregate_id=batch_id,
                                 payload={"from_status": row["status"], "to_status": to_status,
                                          "counts": new_counts}))  # fmt: skip
    return dict(updated)


def reconcile(conn: Conn, ctx: OpContext, batch_id: UUID, check_type: str, subject: str,
              expected: str | None, observed: str | None) -> str:  # fmt: skip
    result = "not_applicable" if expected is None else ("pass" if expected == observed else "fail")
    conn.execute(
        "INSERT INTO legacy.reconciliations (reconciliation_id, tenant_id, batch_id, check_type, subject, expected, "
        "observed, result) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (uuid7(), ctx.tenant_id, batch_id, check_type, subject, expected, observed, result),
    )
    return result


def quarantine(conn: Conn, ctx: OpContext, batch_id: UUID, source_object: str, source_key: str | None,
               reason: str, details: dict[str, Any]) -> None:  # fmt: skip
    conn.execute(
        "INSERT INTO legacy.quarantine (quarantine_id, tenant_id, batch_id, source_object, source_key, reason, "
        "details) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (uuid7(), ctx.tenant_id, batch_id, source_object, source_key, reason, Jsonb(details)),
    )


def list_batches(conn: Conn, ctx: OpContext) -> list[dict[str, Any]]:
    require(conn, ctx.principal, "import:read", Resource("import_batch"))
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM legacy.import_batches ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    ]


def get_batch(conn: Conn, ctx: OpContext, batch_id: UUID) -> dict[str, Any]:
    require(conn, ctx.principal, "import:read", Resource("import_batch", batch_id))
    row = conn.execute("SELECT * FROM legacy.import_batches WHERE batch_id = %s", (batch_id,)).fetchone()
    if not row:
        raise NotFound("Lote não encontrado.")
    recs = conn.execute(
        "SELECT check_type, subject, expected, observed, result, created_at FROM "
        "legacy.reconciliations WHERE batch_id = %s ORDER BY created_at",
        (batch_id,),
    ).fetchall()
    return {**dict(row), "reconciliations": [dict(r) for r in recs]}
