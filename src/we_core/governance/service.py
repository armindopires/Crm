"""Governance & Decisions: a IA propõe, o humano valida, o sistema audita.

Máquina de estados: proposed → under_review → approved|rejected → executed → superseded.
A base de dados reforça transições, segregação de funções e aprovação humana (trigger em 0004).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from we_core.audit import log as audit
from we_core.common import utcnow, uuid7
from we_core.context import OpContext
from we_core.db import Conn
from we_core.errors import Conflict, Forbidden, HumanApprovalRequired, NotFound, ValidationFailed
from we_core.events.store import EventDraft, append
from we_core.evidence import service as evidence
from we_core.identity.authz import Resource, require
from we_core.kernel.service import get_context_frame

IMPACT = {"juridico", "fiscal", "financeiro", "laboral", "reputacional", "externo", "interno"}


def _get(conn: Conn, decision_id: UUID, lock: bool = False) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM governance.decisions WHERE decision_id = %s" + (" FOR UPDATE" if lock else ""),
        (decision_id,),
    ).fetchone()
    if not row:
        raise NotFound("Decisão não encontrada.")
    return dict(row)


def propose(conn: Conn, ctx: OpContext, *, title: str, description: str | None, decision_type: str,
            impact_category: str, context_frame_id: UUID, evidence_ids: list[UUID],
            ai_trace_id: UUID | None = None, organization_id: UUID | None = None,
            idempotency_key: str | None = None) -> dict[str, Any]:  # fmt: skip
    require(conn, ctx.principal, "decision:propose", Resource("decision", organization_id=organization_id))
    if impact_category not in IMPACT:
        raise ValidationFailed(f"Categoria de impacto inválida: {impact_category}")
    if ctx.principal.actor_type == "ai_agent" and ai_trace_id is None:
        raise ValidationFailed("Propostas de IA exigem AI_TRACE associado.", code="WE-GOV-AITRACE")
    get_context_frame(conn, ctx, context_frame_id)
    decision_id = uuid7()
    row = conn.execute(
        """INSERT INTO governance.decisions (decision_id, tenant_id, organization_id, title, description,
             decision_type, impact_category, requires_human_approval, context_frame_id, proposed_by,
             proposed_by_type, ai_trace_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,true,%s,%s,%s,%s) RETURNING *""",
        (decision_id, ctx.tenant_id, organization_id, title, description, decision_type, impact_category,
         context_frame_id, ctx.principal.actor_id, ctx.principal.actor_type, ai_trace_id),
    ).fetchone()  # fmt: skip
    assert row is not None
    for eid in evidence_ids:
        evidence.link(conn, ctx, eid, "decision", decision_id, "supports", as_reference=True)
    append(conn, ctx, EventDraft(
        event_type="governance.decision_proposed", aggregate_type="decision", aggregate_id=decision_id,
        expected_version=0, organization_id=organization_id, context_frame_id=context_frame_id,
        idempotency_key=idempotency_key,
        payload={"decision_type": decision_type, "impact_category": impact_category,
                 "proposed_by_type": ctx.principal.actor_type, "ai_trace_id": ai_trace_id,
                 "evidence_ids": evidence_ids},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="decision.propose",
        resource_type="decision",
        resource_id=decision_id,
        outcome="succeeded",
        context_frame_id=context_frame_id,
        details={"impact_category": impact_category, "evidence_count": len(evidence_ids)},
    )
    return dict(row)


def get(conn: Conn, ctx: OpContext, decision_id: UUID) -> dict[str, Any]:
    row = _get(conn, decision_id)
    require(
        conn,
        ctx.principal,
        "decision:read",
        Resource("decision", decision_id, organization_id=row["organization_id"]),
    )
    row["evidence_ids"] = [
        r["evidence_id"]
        for r in conn.execute(
            "SELECT evidence_id FROM evidence.links WHERE target_type='decision' AND target_id=%s",
            (decision_id,),
        )
    ]
    row["approvals"] = [dict(r) for r in conn.execute(
        "SELECT approval_id, approver_id, verdict, rationale, created_at FROM governance.approvals "
        "WHERE decision_id = %s ORDER BY created_at", (decision_id,))]  # fmt: skip
    return row


def list_decisions(conn: Conn, ctx: OpContext, status: str | None, limit: int) -> list[dict[str, Any]]:
    require(conn, ctx.principal, "decision:read", Resource("decision"))
    if status:
        rows = conn.execute("SELECT * FROM governance.decisions WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                            (status, limit)).fetchall()  # fmt: skip
    else:
        rows = conn.execute(
            "SELECT * FROM governance.decisions ORDER BY created_at DESC LIMIT %s", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def review(conn: Conn, ctx: OpContext, decision_id: UUID, *, verdict: str, rationale: str,
           expected_version: int | None = None) -> dict[str, Any]:  # fmt: skip
    """Aprovação/rejeição humana explícita (HITL)."""
    if verdict not in ("approved", "rejected"):
        raise ValidationFailed("Veredicto tem de ser 'approved' ou 'rejected'.")
    row = _get(conn, decision_id, lock=True)
    require(
        conn,
        ctx.principal,
        "decision:approve",
        Resource("decision", decision_id, organization_id=row["organization_id"]),
        ctx.purpose,
    )
    if ctx.principal.actor_type != "human":
        raise Forbidden("Só um humano pode aprovar ou rejeitar decisões.", code="WE-GOV-HITL")
    if row["proposed_by"] == ctx.principal.actor_id:
        raise Forbidden(
            "Segregação de funções: o proponente não pode decidir a própria proposta.", code="WE-GOV-SOD"
        )
    if row["status"] not in ("proposed", "under_review"):
        raise Conflict(f"Decisão em estado '{row['status']}' não pode ser revista.", code="WE-GOV-STATE")
    if expected_version is not None and row["version"] != expected_version:
        raise Conflict("Versão da decisão desatualizada.", code="WE-GOV-VERSION")
    approval_id = uuid7()
    conn.execute(
        "INSERT INTO governance.approvals (approval_id, tenant_id, decision_id, approver_id, verdict, rationale) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (approval_id, ctx.tenant_id, decision_id, ctx.principal.actor_id, verdict, rationale),
    )
    updated = conn.execute(
        "UPDATE governance.decisions SET status = %s, decided_by = %s, decided_at = %s, rationale = %s "
        "WHERE decision_id = %s RETURNING *",
        (verdict, ctx.principal.actor_id, utcnow(), rationale, decision_id),
    ).fetchone()
    assert updated is not None
    append(conn, ctx, EventDraft(
        event_type=f"governance.decision_{verdict}", aggregate_type="decision", aggregate_id=decision_id,
        organization_id=row["organization_id"], context_frame_id=row["context_frame_id"],
        payload={"approval_id": approval_id, "from_status": row["status"]},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action={"approved": "decision.approve", "rejected": "decision.reject"}[verdict],
        resource_type="decision",
        resource_id=decision_id,
        outcome="succeeded",
        reason=rationale,
        context_frame_id=row["context_frame_id"],
        policy_refs=["hitl:human_approval", "sod:proposer_not_approver"],
    )
    return dict(updated)


def execute(conn: Conn, ctx: OpContext, decision_id: UUID) -> dict[str, Any]:
    """Execução registada (recorded_only): nesta fase não há efeitos externos reais."""
    row = _get(conn, decision_id, lock=True)
    require(
        conn,
        ctx.principal,
        "decision:execute",
        Resource("decision", decision_id, organization_id=row["organization_id"]),
    )
    if row["status"] != "approved":
        raise HumanApprovalRequired(
            f"A decisão está em '{row['status']}'. Nenhuma ação material é executada sem aprovação humana.",
            extra={"decision_id": str(decision_id), "status": row["status"]})  # fmt: skip
    updated = conn.execute(
        "UPDATE governance.decisions SET status = 'executed', executed_by = %s, executed_at = %s "
        "WHERE decision_id = %s RETURNING *",
        (ctx.principal.actor_id, utcnow(), decision_id),
    ).fetchone()
    assert updated is not None
    append(conn, ctx, EventDraft(
        event_type="governance.decision_executed", aggregate_type="decision", aggregate_id=decision_id,
        organization_id=row["organization_id"], context_frame_id=row["context_frame_id"],
        payload={"execution_mode": "recorded_only"},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="decision.execute",
        resource_type="decision",
        resource_id=decision_id,
        outcome="succeeded",
        context_frame_id=row["context_frame_id"],
        details={"execution_mode": "recorded_only"},
    )
    return dict(updated)
