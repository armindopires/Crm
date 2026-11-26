"""Intelligence, Signals & Opportunities: SIGNAL detetado → promovido a OPPORTUNITY (piloto)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from we_core.audit import log as audit
from we_core.common import uuid7
from we_core.context import OpContext
from we_core.db import Conn
from we_core.errors import Conflict, NotFound, ValidationFailed
from we_core.events.store import EventDraft, append
from we_core.identity.authz import Resource, require, scope_sql


def create_signal(
    conn: Conn,
    ctx: OpContext,
    *,
    signal_type: str,
    source: str,
    strength: str,
    description: str,
    entity_id: UUID | None,
    context_frame_id: UUID | None,
    organization_id: UUID | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    require(conn, ctx.principal, "signal:write", Resource("signal", organization_id=organization_id))
    try:
        s = Decimal(strength)
    except InvalidOperation as exc:
        raise ValidationFailed("Intensidade inválida.") from exc
    if not (Decimal(0) <= s <= Decimal(1)):
        raise ValidationFailed("Intensidade tem de estar entre 0 e 1.")
    signal_id = uuid7()
    row = conn.execute(
        """INSERT INTO intelligence.signals (signal_id, tenant_id, organization_id, signal_type, source, strength,
             entity_id, context_frame_id, description, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (signal_id, ctx.tenant_id, organization_id, signal_type, source, s, entity_id, context_frame_id,
         description, ctx.principal.actor_id),
    ).fetchone()  # fmt: skip
    assert row is not None
    append(conn, ctx, EventDraft(
        event_type="intelligence.signal_detected", aggregate_type="signal", aggregate_id=signal_id,
        expected_version=0, organization_id=organization_id, context_frame_id=context_frame_id,
        idempotency_key=idempotency_key,
        payload={"signal_type": signal_type, "source": source, "strength": str(s), "entity_id": entity_id},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="signal.create",
        resource_type="signal",
        resource_id=signal_id,
        outcome="succeeded",
        context_frame_id=context_frame_id,
    )
    return dict(row)


def promote(conn: Conn, ctx: OpContext, signal_id: UUID, *, title: str, value_estimate: str | None,
            currency: str | None) -> dict[str, Any]:  # fmt: skip
    require(conn, ctx.principal, "opportunity:write", Resource("opportunity"))
    sig = conn.execute(
        "SELECT * FROM intelligence.signals WHERE signal_id = %s FOR UPDATE", (signal_id,)
    ).fetchone()
    if not sig:
        raise NotFound("Sinal não encontrado.")
    require(
        conn,
        ctx.principal,
        "opportunity:write",
        Resource("signal", signal_id, organization_id=sig["organization_id"]),
    )
    if sig["status"] == "promoted":
        raise Conflict("Sinal já promovido a oportunidade.", code="WE-INT-409")
    if (value_estimate is None) != (currency is None):
        raise ValidationFailed("Valor estimado e moeda (ISO 4217) têm de ser indicados em conjunto.")
    value = Decimal(value_estimate).quantize(Decimal("0.01")) if value_estimate is not None else None
    opp_id = uuid7()
    row = conn.execute(
        """INSERT INTO intelligence.opportunities (opportunity_id, tenant_id, signal_id, title, value_estimate,
             currency, owner_actor_id) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (opp_id, ctx.tenant_id, signal_id, title, value, currency, ctx.principal.actor_id),
    ).fetchone()  # fmt: skip
    assert row is not None
    conn.execute("UPDATE intelligence.signals SET status = 'promoted', version = version + 1 WHERE signal_id = %s",
                 (signal_id,))  # fmt: skip
    append(conn, ctx, EventDraft(
        event_type="intelligence.opportunity_identified", aggregate_type="signal", aggregate_id=signal_id,
        organization_id=sig["organization_id"], context_frame_id=sig["context_frame_id"],
        payload={"opportunity_id": opp_id, "signal_id": signal_id,
                 "value_estimate": str(value) if value is not None else None, "currency": currency},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="signal.promote",
        resource_type="opportunity",
        resource_id=opp_id,
        outcome="succeeded",
        details={"signal_id": str(signal_id)},
    )
    return dict(row)


def list_signals(conn: Conn, ctx: OpContext, limit: int) -> list[dict[str, Any]]:
    require(conn, ctx.principal, "signal:read", Resource("signal"))
    where, params = scope_sql(ctx.principal)
    sql = f"SELECT * FROM intelligence.signals WHERE {where} ORDER BY created_at DESC LIMIT %s"
    return [dict(r) for r in conn.execute(sql.encode(), (*params, limit)).fetchall()]


def list_opportunities(conn: Conn, ctx: OpContext, limit: int) -> list[dict[str, Any]]:
    require(conn, ctx.principal, "opportunity:read", Resource("opportunity"))
    where, params = scope_sql(ctx.principal, org_col="s.organization_id")
    sql = (
        "SELECT o.* FROM intelligence.opportunities o JOIN intelligence.signals s "
        f"ON s.tenant_id = o.tenant_id AND s.signal_id = o.signal_id WHERE {where} "
        "ORDER BY o.created_at DESC LIMIT %s"
    )
    return [dict(r) for r in conn.execute(sql.encode(), (*params, limit)).fetchall()]
