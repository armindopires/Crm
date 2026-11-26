"""Rotas: eventos, replay, integridade, evidências, decisões, IA, sinais, auditoria, fontes e lotes."""

from __future__ import annotations

import dataclasses
import hashlib
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from we_core.ai import gateway
from we_core.api import models as m
from we_core.api.deps import idempotency_key, op_context, run_idempotent, state, tenant_conn
from we_core.context import OpContext
from we_core.db import Conn
from we_core.errors import NotFound, ValidationFailed
from we_core.events import projections
from we_core.evidence import service as evidence
from we_core.governance import service as governance
from we_core.identity.authz import Resource, require
from we_core.integrity import verify_audit, verify_events
from we_core.intelligence import service as intelligence
from we_core.legacy import service as legacy
from we_core.observability import metrics

router = APIRouter(prefix="/v1")


# ── Events ──
@router.get("/events", response_model=m.Page[m.EventOut], tags=["events"])
def list_events(after_seq: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                correlation_id: UUID | None = None, aggregate_id: UUID | None = None,
                event_type: str | None = None, ctx: OpContext = Depends(op_context),
                conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    require(conn, ctx.principal, "event:read", Resource("event"))
    clauses: list[str] = ["chain_seq > %s"]
    params: list[object] = [after_seq]
    for col, val in (("correlation_id", correlation_id), ("aggregate_id", aggregate_id),
                     ("event_type", event_type)):  # fmt: skip
        if val is not None:
            clauses.append(f"{col} = %s")
            params.append(val)
    rank = ctx.principal.clearance_rank()
    clauses.append(
        "array_position(ARRAY['public','internal','confidential','restricted','secret'], "
        "classification) - 1 <= %s"
    )
    params.append(rank)
    rows = conn.execute(
        f"SELECT * FROM event_store.events WHERE {' AND '.join(clauses)} ORDER BY chain_seq LIMIT %s".encode(),
        (*params, limit),
    ).fetchall()
    return {"items": rows, "next_cursor": str(rows[-1]["chain_seq"]) if len(rows) == limit else None}


@router.get("/events/verify", response_model=m.ChainReportOut, tags=["events"],
            summary="Verificar cadeia de integridade do Event Store")  # fmt: skip
def verify_event_chain(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    require(conn, ctx.principal, "event:verify", Resource("event"))
    rep = verify_events(conn, ctx.tenant_id)
    if not rep.valid:
        metrics.integrity_failures.labels("events").inc()
    return dataclasses.asdict(rep)


@router.post("/admin/projections/{name}/replay", response_model=m.ReplayOut, tags=["events"],
             summary="Reconstruir projeção por replay (administrativo, auditado)")  # fmt: skip
def replay(name: str, ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    require(conn, ctx.principal, "projection:replay", Resource("projection", name))
    if name != projections.PROJECTION:
        raise NotFound("Projeção desconhecida.")
    from we_core.audit import log as audit

    out = projections.replay(conn, ctx.tenant_id)
    audit.record(
        conn,
        ctx,
        action="projection.replay",
        resource_type="projection",
        resource_id=name,
        outcome="succeeded",
        details={"events": out["events_replayed"], "after": out["after"]},
    )
    return out


@router.get("/admin/outbox", response_model=m.OutboxStatusOut, tags=["events"])
def outbox_status(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    require(conn, ctx.principal, "event:read", Resource("outbox"))
    row = conn.execute(
        "SELECT count(*) FILTER (WHERE status='pending') AS pending, count(*) FILTER (WHERE status='published') "
        "AS published, count(*) FILTER (WHERE status='dead') AS dead FROM event_store.outbox").fetchone()  # fmt: skip
    assert row is not None
    return {**row, "projection_lag": projections.lag(conn, ctx.tenant_id)}


@router.post("/admin/outbox/requeue-dead", tags=["events"], summary="Repor mensagens da DLQ (auditado)")
def requeue_dead(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> dict[str, int]:
    require(conn, ctx.principal, "outbox:admin", Resource("outbox"))
    from we_core.audit import log as audit

    rows = conn.execute("UPDATE event_store.outbox SET status='pending', attempts=0, next_attempt_at=now() "
                        "WHERE status='dead' RETURNING event_id").fetchall()  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="outbox.requeue_dead",
        resource_type="outbox",
        resource_id=None,
        outcome="succeeded",
        details={"count": len(rows)},
    )
    return {"requeued": len(rows)}


# ── Evidence ──
@router.post("/evidence", response_model=m.EvidenceOut, status_code=201, tags=["evidence"],
             summary="Carregar evidência (SHA-256 calculado no servidor)")  # fmt: skip
async def upload_evidence(request: Request, file: UploadFile = File(...),
                          classification: m.Classification = Form("confidential"),
                          source: str = Form("upload", max_length=120),
                          organization_id: UUID | None = Form(None),
                          ctx: OpContext = Depends(op_context),
                          idem: str | None = Depends(idempotency_key)) -> Any:  # fmt: skip
    st = state(request)
    limit = st.settings.evidence_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ValidationFailed(f"Evidência excede o limite de {limit} bytes.", code="WE-EVD-SIZE")
    media_type = (file.content_type or "application/octet-stream").split(";")[0].strip().lower()
    with st.db.tenant_tx(ctx.tenant_id) as conn:
        body = {"sha256_of_upload": hashlib.sha256(data).hexdigest(), "c": classification,
                "s": source, "o": str(organization_id)}  # fmt: skip
        out = run_idempotent(conn, ctx, request, idem, body, lambda: evidence.register(
            conn, ctx, st.storage, data=data, filename=file.filename, media_type=media_type,
            classification=classification, source=source, max_bytes=limit, organization_id=organization_id,
            idempotency_key=idem))  # fmt: skip
    metrics.evidence_uploads.inc()
    return out


@router.get("/evidence", response_model=m.Page[m.EvidenceOut], tags=["evidence"])
def list_evidence(limit: int = Query(50, ge=1, le=200), ctx: OpContext = Depends(op_context),
                  conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    require(conn, ctx.principal, "evidence:read", Resource("evidence"))
    rows = conn.execute(
        "SELECT * FROM evidence.evidence WHERE array_position(ARRAY['public','internal','confidential',"
        "'restricted','secret'], classification) - 1 <= %s ORDER BY uploaded_at DESC LIMIT %s",
        (ctx.principal.clearance_rank(), limit)).fetchall()  # fmt: skip
    return {"items": rows}


@router.get("/evidence/{evidence_id}", response_model=m.EvidenceOut, tags=["evidence"])
def get_evidence(
    evidence_id: UUID, ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)
) -> Any:
    return evidence.get(conn, ctx, evidence_id)


@router.get("/evidence/{evidence_id}/custody", response_model=m.Page[m.CustodyOut], tags=["evidence"])
def get_custody(
    evidence_id: UUID, ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)
) -> Any:
    return {"items": evidence.custody(conn, ctx, evidence_id)}


@router.post("/evidence/{evidence_id}/links", status_code=201, tags=["evidence"])
def link_evidence(evidence_id: UUID, body: m.EvidenceLinkCreate, ctx: OpContext = Depends(op_context),
                  conn: Conn = Depends(tenant_conn)) -> dict[str, Any]:  # fmt: skip
    return evidence.link(conn, ctx, evidence_id, body.target_type, body.target_id, body.link_type)


@router.post("/evidence/{evidence_id}/verify", response_model=m.EvidenceVerifyOut, tags=["evidence"],
             summary="Recalcular SHA-256 do objeto guardado e comparar")  # fmt: skip
def verify_evidence(evidence_id: UUID, request: Request, ctx: OpContext = Depends(op_context),
                    conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    out = evidence.verify(conn, ctx, state(request).storage, evidence_id)
    if not out["valid"]:
        metrics.integrity_failures.labels("evidence").inc()
    return out


# ── Governance ──
@router.post("/decisions", response_model=m.DecisionOut, status_code=201, tags=["governance"])
def propose_decision(body: m.DecisionCreate, request: Request, ctx: OpContext = Depends(op_context),
                     conn: Conn = Depends(tenant_conn), idem: str | None = Depends(idempotency_key)) -> Any:  # fmt: skip
    return run_idempotent(
        conn,
        ctx,
        request,
        idem,
        body.model_dump(mode="json"),
        lambda: governance.propose(conn, ctx, idempotency_key=idem, **body.model_dump()),
    )


@router.get("/decisions", response_model=m.Page[m.DecisionOut], tags=["governance"])
def list_decisions(status: str | None = None, limit: int = Query(50, ge=1, le=200),
                   ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    return {"items": governance.list_decisions(conn, ctx, status, limit)}


@router.get("/decisions/{decision_id}", response_model=m.DecisionOut, tags=["governance"])
def get_decision(
    decision_id: UUID, ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)
) -> Any:
    return governance.get(conn, ctx, decision_id)


@router.post("/decisions/{decision_id}/review", response_model=m.DecisionOut, tags=["governance"],
             summary="Aprovação ou rejeição humana explícita (HITL)")  # fmt: skip
def review_decision(decision_id: UUID, body: m.DecisionReview, ctx: OpContext = Depends(op_context),
                    conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    return governance.review(conn, ctx, decision_id, **body.model_dump())


@router.post("/decisions/{decision_id}/execute", response_model=m.DecisionOut, tags=["governance"],
             summary="Executar decisão aprovada (registo apenas; sem efeitos externos)")  # fmt: skip
def execute_decision(
    decision_id: UUID, ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)
) -> Any:
    return governance.execute(conn, ctx, decision_id)


@router.post("/ai/invoke", response_model=m.AIInvokeOut, tags=["ai"],
             summary="Invocar capacidade de IA autorizada (gera AI_TRACE)")  # fmt: skip
def ai_invoke(
    body: m.AIInvoke, ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)
) -> Any:
    return gateway.invoke(
        conn,
        ctx,
        gateway.LocalHeuristicProvider(),
        capability=body.capability,
        text=body.text,
        params=body.params,
    )


# ── Intelligence ──
@router.post("/signals", response_model=m.SignalOut, status_code=201, tags=["intelligence"])
def create_signal(body: m.SignalCreate, request: Request, ctx: OpContext = Depends(op_context),
                  conn: Conn = Depends(tenant_conn), idem: str | None = Depends(idempotency_key)) -> Any:  # fmt: skip
    return run_idempotent(
        conn,
        ctx,
        request,
        idem,
        body.model_dump(mode="json"),
        lambda: intelligence.create_signal(conn, ctx, idempotency_key=idem, **body.model_dump()),
    )


@router.get("/signals", response_model=m.Page[m.SignalOut], tags=["intelligence"])
def list_signals(limit: int = Query(50, ge=1, le=200), ctx: OpContext = Depends(op_context),
                 conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    return {"items": intelligence.list_signals(conn, ctx, limit)}


@router.post("/signals/{signal_id}/promote", response_model=m.OpportunityOut, status_code=201,
             tags=["intelligence"])  # fmt: skip
def promote_signal(signal_id: UUID, body: m.SignalPromote, ctx: OpContext = Depends(op_context),
                   conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    return intelligence.promote(conn, ctx, signal_id, **body.model_dump())


@router.get("/opportunities", response_model=m.Page[m.OpportunityOut], tags=["intelligence"])
def list_opps(limit: int = Query(50, ge=1, le=200), ctx: OpContext = Depends(op_context),
              conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    return {"items": intelligence.list_opportunities(conn, ctx, limit)}


# ── Audit ──
@router.get("/audit", response_model=m.Page[m.AuditOut], tags=["audit"])
def list_audit(after_seq: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
               correlation_id: UUID | None = None, ctx: OpContext = Depends(op_context),
               conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    require(conn, ctx.principal, "audit:read", Resource("audit"))
    if correlation_id:
        rows = conn.execute("SELECT * FROM audit.audit_log WHERE chain_seq > %s AND correlation_id = %s "
                            "ORDER BY chain_seq LIMIT %s", (after_seq, correlation_id, limit)).fetchall()  # fmt: skip
    else:
        rows = conn.execute("SELECT * FROM audit.audit_log WHERE chain_seq > %s ORDER BY chain_seq LIMIT %s",
                            (after_seq, limit)).fetchall()  # fmt: skip
    return {"items": rows, "next_cursor": str(rows[-1]["chain_seq"]) if len(rows) == limit else None}


@router.get("/audit/verify", response_model=m.ChainReportOut, tags=["audit"],
            summary="Verificar cadeia de hashes do registo de auditoria")  # fmt: skip
def verify_audit_chain(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    require(conn, ctx.principal, "audit:verify", Resource("audit"))
    rep = verify_audit(conn, ctx.tenant_id)
    if not rep.valid:
        metrics.integrity_failures.labels("audit").inc()
    return dataclasses.asdict(rep)


# ── Knowledge & Legacy ──
@router.get("/source-systems", response_model=m.Page[m.SourceSystemOut], tags=["legacy"])
def source_systems(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    require(conn, ctx.principal, "source:read", Resource("source_system"))
    return {
        "items": conn.execute("SELECT * FROM legacy.source_systems ORDER BY source_system_code").fetchall()
    }


@router.get("/sources", response_model=m.Page[m.SourceOut], tags=["knowledge"])
def list_sources(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    require(conn, ctx.principal, "source:read", Resource("source"))
    return {
        "items": conn.execute(
            "SELECT * FROM knowledge.sources ORDER BY registered_at DESC LIMIT 200"
        ).fetchall()
    }


@router.post("/import-batches", response_model=m.ImportBatchOut, status_code=201, tags=["legacy"],
             summary="Criar lote de staging (sem ligação a bases reais)")  # fmt: skip
def create_batch(body: m.ImportBatchCreate, ctx: OpContext = Depends(op_context),
                 conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    return legacy.create_batch(conn, ctx, **body.model_dump())


@router.get("/import-batches", response_model=m.Page[m.ImportBatchOut], tags=["legacy"])
def list_batches(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    return {"items": legacy.list_batches(conn, ctx)}


@router.get("/import-batches/{batch_id}", response_model=m.ImportBatchOut, tags=["legacy"])
def get_batch(batch_id: UUID, ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    return legacy.get_batch(conn, ctx, batch_id)


# ── Estado agregado para a interface operacional ──
@router.get("/system/status", response_model=m.SystemStatusOut, tags=["system"])
def system_status(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    from we_core.platform.service import get_tenant

    tenant = get_tenant(conn, ctx)
    counts = conn.execute(
        """SELECT (SELECT count(*) FROM kernel.entities) AS entities,
                  (SELECT count(*) FROM event_store.events) AS events,
                  (SELECT count(*) FROM evidence.evidence) AS evidence,
                  (SELECT count(*) FROM governance.decisions WHERE status IN ('proposed','under_review'))
                     AS decisions_pending,
                  (SELECT count(*) FROM intelligence.signals) AS signals,
                  (SELECT count(*) FROM intelligence.opportunities) AS opportunities,
                  (SELECT count(*) FROM legacy.import_batches) AS import_batches,
                  (SELECT count(*) FROM audit.audit_log) AS audit_records""").fetchone()  # fmt: skip
    assert counts is not None
    ob = outbox_status(ctx, conn)
    chains = {
        "events": verify_events(conn, ctx.tenant_id).valid,
        "audit": verify_audit(conn, ctx.tenant_id).valid,
    }
    return {"tenant": tenant, "counts": counts, "outbox": ob, "chains": chains}


@router.get("/projections/entity-summary/{entity_id}", tags=["events"],
            summary="Ler projeção entity_summary de uma entidade")  # fmt: skip
def entity_summary(entity_id: UUID, ctx: OpContext = Depends(op_context),
                   conn: Conn = Depends(tenant_conn)) -> dict[str, Any]:  # fmt: skip
    require(conn, ctx.principal, "entity:read", Resource("projection"))
    row = conn.execute("SELECT entity_id, entity_type, event_count, last_event_type, last_aggregate_version, "
                       "last_chain_seq, last_event_at FROM projection.entity_summary WHERE entity_id = %s",
                       (entity_id,)).fetchone()  # fmt: skip
    if not row:
        raise NotFound("Sem projeção para esta entidade (ainda não processada?).")
    return dict(row)
