"""Registo de auditoria: quem, o quê, quando, onde, porquê, política, resultado e correlação.

Nunca guarda PII em claro: sujeitos IdP e origens são pseudonimizados por HMAC (ver data-classification.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from we_core.common import chain_hash, iso_utc, pseudonymize, to_jsonable, utcnow, uuid7
from we_core.config import get_settings
from we_core.context import OpContext
from we_core.db import Conn
from we_core.events.store import advance_chain, lock_chain

AUDIT_HASHED = (
    "audit_id", "tenant_id", "chain_seq", "occurred_at", "actor_id", "actor_type", "actor_ref", "action",
    "resource_type", "resource_id", "outcome", "reason", "policy_refs", "context_frame_id", "correlation_id",
    "trace_id", "origin_ref", "details",
)  # fmt: skip


def audit_hash_record(row: dict[str, Any]) -> dict[str, Any]:
    rec = {k: row.get(k) for k in AUDIT_HASHED}
    occurred = rec["occurred_at"]
    if isinstance(occurred, datetime):
        rec["occurred_at"] = iso_utc(occurred)
    return to_jsonable(rec)  # type: ignore[no-any-return]


def record(
    conn: Conn,
    ctx: OpContext,
    *,
    action: str,
    resource_type: str,
    resource_id: UUID | str | None,
    outcome: str,
    reason: str | None = None,
    policy_refs: list[str] | None = None,
    context_frame_id: UUID | None = None,
    details: dict[str, Any] | None = None,
    tenant_id: UUID | None = None,
) -> dict[str, Any]:
    tid = tenant_id or ctx.tenant_id
    key = get_settings().audit_pseudonym_key.get_secret_value() or "dev-only-pseudonym-key"
    last_seq, last_hash = lock_chain(conn, tid, "audit")
    row: dict[str, Any] = {
        "audit_id": uuid7(),
        "tenant_id": tid,
        "chain_seq": last_seq + 1,
        "occurred_at": utcnow(),
        "actor_id": ctx.principal.actor_id,
        "actor_type": ctx.principal.actor_type,
        "actor_ref": pseudonymize(key, ctx.principal.subject),
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "outcome": outcome,
        "reason": reason,
        "policy_refs": policy_refs or [],
        "context_frame_id": context_frame_id,
        "correlation_id": ctx.correlation_id,
        "trace_id": ctx.trace_id,
        "origin_ref": pseudonymize(key, ctx.origin) if ctx.origin else None,
        "details": to_jsonable(details or {}),
    }
    row["previous_hash"] = last_hash
    row["record_hash"] = chain_hash(last_hash, audit_hash_record(row))
    params = {**row, "policy_refs": Jsonb(row["policy_refs"]), "details": Jsonb(row["details"])}
    conn.execute(
        """INSERT INTO audit.audit_log (audit_id, tenant_id, chain_seq, occurred_at, actor_id, actor_type,
             actor_ref, action, resource_type, resource_id, outcome, reason, policy_refs, context_frame_id,
             correlation_id, trace_id, origin_ref, details, previous_hash, record_hash)
           VALUES (%(audit_id)s, %(tenant_id)s, %(chain_seq)s, %(occurred_at)s, %(actor_id)s, %(actor_type)s,
             %(actor_ref)s, %(action)s, %(resource_type)s, %(resource_id)s, %(outcome)s, %(reason)s,
             %(policy_refs)s, %(context_frame_id)s, %(correlation_id)s, %(trace_id)s, %(origin_ref)s,
             %(details)s, %(previous_hash)s, %(record_hash)s)""",
        params,
    )
    advance_chain(conn, tid, "audit", row["chain_seq"], row["record_hash"])
    return row
