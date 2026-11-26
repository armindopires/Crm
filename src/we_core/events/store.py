"""Event Store append-only sobre PostgreSQL.

Garantias:
- payload validado por JSON Schema versionado antes de gravar;
- concorrência otimista por (aggregate_type, aggregate_id, aggregate_version);
- idempotência por (tenant_id, idempotency_key): repetir a chave devolve o evento original;
- cadeia de hashes por tenant (previous_hash → event_hash), serializada pela cabeça da cadeia;
- outbox escrita na mesma transação (entrega at-least-once ao EventBus).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from we_core.common import GENESIS_HASH, chain_hash, iso_utc, to_jsonable, utcnow, uuid7
from we_core.context import OpContext
from we_core.db import Conn
from we_core.errors import ConcurrencyConflict, ValidationFailed
from we_core.events.registry import get_registry

HASHED_FIELDS = (
    "event_id", "tenant_id", "organization_id", "chain_seq", "event_type", "schema_version",
    "aggregate_type", "aggregate_id", "aggregate_version", "context_frame_id", "actor_id", "actor_type",
    "occurred_at", "recorded_at", "correlation_id", "causation_id", "trace_id", "idempotency_key",
    "classification", "payload", "metadata",
)  # fmt: skip


@dataclass
class EventDraft:
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    payload: dict[str, Any]
    schema_version: int | None = None
    expected_version: int | None = None  # None = sem verificação; 0 = agregado novo
    organization_id: UUID | None = None
    context_frame_id: UUID | None = None
    idempotency_key: str | None = None
    classification: str = "internal"
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppendResult:
    event: dict[str, Any]
    duplicate: bool


def hash_record(row: dict[str, Any]) -> dict[str, Any]:
    rec = {k: row.get(k) for k in HASHED_FIELDS}
    for k in ("occurred_at", "recorded_at"):
        value = rec[k]
        if isinstance(value, datetime):
            rec[k] = iso_utc(value)
    return to_jsonable(rec)  # type: ignore[no-any-return]


def _reject_floats(obj: Any, path: str) -> None:
    """Floats não fazem round-trip exato em JSONB: valores numéricos não inteiros circulam como texto decimal."""
    if isinstance(obj, float):
        raise ValidationFailed(f"Float não permitido em {path}; use texto decimal.", code="WE-EVT-FLOAT")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_floats(v, f"{path}.{k}")
    elif isinstance(obj, list | tuple):
        for i, v in enumerate(obj):
            _reject_floats(v, f"{path}[{i}]")


def subject_for(event: dict[str, Any]) -> str:
    return f"we.{event['tenant_id']}.{event['event_type']}"


def lock_chain(conn: Conn, tenant_id: UUID, chain: str) -> tuple[int, str]:
    conn.execute(
        "INSERT INTO platform.chain_heads (tenant_id, chain_name, last_seq, last_hash) "
        "VALUES (%s, %s, 0, %s) ON CONFLICT DO NOTHING",
        (tenant_id, chain, GENESIS_HASH),
    )
    row = conn.execute(
        "SELECT last_seq, last_hash FROM platform.chain_heads WHERE tenant_id = %s AND chain_name = %s FOR UPDATE",
        (tenant_id, chain),
    ).fetchone()
    assert row is not None
    return int(row["last_seq"]), str(row["last_hash"])


def advance_chain(conn: Conn, tenant_id: UUID, chain: str, seq: int, h: str) -> None:
    conn.execute(
        "UPDATE platform.chain_heads SET last_seq = %s, last_hash = %s, updated_at = now() "
        "WHERE tenant_id = %s AND chain_name = %s",
        (seq, h, tenant_id, chain),
    )


def append(conn: Conn, ctx: OpContext, draft: EventDraft) -> AppendResult:
    registry = get_registry()
    version = draft.schema_version or registry.latest_version(draft.event_type)
    _reject_floats(draft.payload, "payload")
    payload = to_jsonable(draft.payload)
    registry.validate(draft.event_type, version, payload)
    tenant_id = ctx.tenant_id

    last_seq, last_hash = lock_chain(conn, tenant_id, "events")

    if draft.idempotency_key:
        existing = conn.execute(
            "SELECT * FROM event_store.events WHERE tenant_id = %s AND idempotency_key = %s",
            (tenant_id, draft.idempotency_key),
        ).fetchone()
        if existing:
            return AppendResult(existing, duplicate=True)

    cur = conn.execute(
        "SELECT coalesce(max(aggregate_version), 0) AS v FROM event_store.events "
        "WHERE tenant_id = %s AND aggregate_type = %s AND aggregate_id = %s",
        (tenant_id, draft.aggregate_type, draft.aggregate_id),
    ).fetchone()
    current = int(cur["v"]) if cur else 0
    if draft.expected_version is not None and draft.expected_version != current:
        raise ConcurrencyConflict(
            f"Versão esperada {draft.expected_version}, versão atual {current} "
            f"para {draft.aggregate_type}/{draft.aggregate_id}.",
            extra={"current_version": current},
        )

    now = utcnow()
    row: dict[str, Any] = {
        "event_id": uuid7(),
        "tenant_id": tenant_id,
        "organization_id": draft.organization_id,
        "chain_seq": last_seq + 1,
        "event_type": draft.event_type,
        "schema_version": version,
        "aggregate_type": draft.aggregate_type,
        "aggregate_id": draft.aggregate_id,
        "aggregate_version": current + 1,
        "context_frame_id": draft.context_frame_id,
        "actor_id": ctx.principal.actor_id,
        "actor_type": ctx.principal.actor_type,
        "occurred_at": draft.occurred_at or now,
        "recorded_at": now,
        "correlation_id": ctx.correlation_id,
        "causation_id": ctx.causation_id,
        "trace_id": ctx.trace_id,
        "idempotency_key": draft.idempotency_key,
        "classification": draft.classification,
        "payload": payload,
        "metadata": to_jsonable(draft.metadata),
    }
    row["previous_hash"] = last_hash
    row["event_hash"] = chain_hash(last_hash, hash_record(row))

    from psycopg.types.json import Jsonb

    params = {**row, "payload": Jsonb(row["payload"]), "metadata": Jsonb(row["metadata"])}
    stored = conn.execute(
        """INSERT INTO event_store.events (event_id, tenant_id, organization_id, chain_seq, event_type,
             schema_version, aggregate_type, aggregate_id, aggregate_version, context_frame_id, actor_id,
             actor_type, occurred_at, recorded_at, correlation_id, causation_id, trace_id, idempotency_key,
             classification, payload, metadata, previous_hash, event_hash)
           VALUES (%(event_id)s, %(tenant_id)s, %(organization_id)s, %(chain_seq)s, %(event_type)s,
             %(schema_version)s, %(aggregate_type)s, %(aggregate_id)s, %(aggregate_version)s,
             %(context_frame_id)s, %(actor_id)s, %(actor_type)s, %(occurred_at)s, %(recorded_at)s,
             %(correlation_id)s, %(causation_id)s, %(trace_id)s, %(idempotency_key)s, %(classification)s,
             %(payload)s, %(metadata)s, %(previous_hash)s, %(event_hash)s)
           RETURNING *""",
        params,
    ).fetchone()
    assert stored is not None
    conn.execute(
        "INSERT INTO event_store.outbox (event_id, tenant_id, subject) VALUES (%s, %s, %s)",
        (row["event_id"], tenant_id, subject_for(row)),
    )
    advance_chain(conn, tenant_id, "events", row["chain_seq"], row["event_hash"])
    return AppendResult(stored, duplicate=False)


def envelope(row: dict[str, Any]) -> dict[str, Any]:
    """Representação pública (EventBus/API) de um evento gravado."""
    out = hash_record(row)
    out["chain_seq"] = row["chain_seq"]
    out["previous_hash"] = row["previous_hash"]
    out["event_hash"] = row["event_hash"]
    return out
