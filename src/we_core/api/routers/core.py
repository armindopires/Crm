"""Rotas: tenancy, IAM, kernel (entidades, papéis, relações, context frames)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from we_core.api import models as m
from we_core.api.deps import idempotency_key, op_context, run_idempotent, state, tenant_conn
from we_core.context import OpContext
from we_core.db import Conn
from we_core.errors import PreconditionFailed, ValidationFailed
from we_core.kernel import service as kernel
from we_core.platform import service as platform

router = APIRouter(prefix="/v1")


@router.post("/tenants", response_model=m.TenantCreated, status_code=201, tags=["tenancy"],
             summary="Criar tenant (administrador de plataforma)")  # fmt: skip
def create_tenant(body: m.TenantCreate, request: Request, ctx: OpContext = Depends(op_context)) -> Any:
    return platform.create_tenant(state(request).db, ctx, **body.model_dump())


@router.get("/tenant", response_model=m.TenantOut, tags=["tenancy"], summary="Tenant do token")
def get_tenant(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    return platform.get_tenant(conn, ctx)


@router.get("/organizations", response_model=m.Page[m.OrganizationOut], tags=["tenancy"])
def list_orgs(ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    return {"items": platform.list_organizations(conn, ctx)}


@router.post("/organizations", response_model=m.OrganizationOut, status_code=201, tags=["tenancy"])
def create_org(body: m.OrganizationCreate, request: Request, ctx: OpContext = Depends(op_context),
               conn: Conn = Depends(tenant_conn), idem: str | None = Depends(idempotency_key)) -> Any:  # fmt: skip
    return run_idempotent(
        conn,
        ctx,
        request,
        idem,
        body.model_dump(),
        lambda: platform.create_organization(conn, ctx, **body.model_dump()),
    )


@router.post("/actors", response_model=m.ActorOut, status_code=201, tags=["iam"])
def create_actor(body: m.ActorCreate, request: Request, ctx: OpContext = Depends(op_context),
                 conn: Conn = Depends(tenant_conn), idem: str | None = Depends(idempotency_key)) -> Any:  # fmt: skip
    return run_idempotent(
        conn,
        ctx,
        request,
        idem,
        body.model_dump(),
        lambda: platform.create_actor(conn, ctx, **body.model_dump()),
    )


@router.post("/policies", response_model=m.PolicyOut, status_code=201, tags=["iam"],
             summary="Publicar nova versão de política ABAC (deny)")  # fmt: skip
def create_policy(body: m.PolicyCreate, request: Request, ctx: OpContext = Depends(op_context),
                  conn: Conn = Depends(tenant_conn), idem: str | None = Depends(idempotency_key)) -> Any:  # fmt: skip
    return run_idempotent(
        conn,
        ctx,
        request,
        idem,
        body.model_dump(),
        lambda: platform.create_policy(conn, ctx, **body.model_dump()),
    )


@router.post("/context-frames", response_model=m.ContextFrameOut, status_code=201, tags=["kernel"],
             summary="Criar nova versão imutável de CONTEXT_FRAME")  # fmt: skip
def create_frame(body: m.ContextFrameCreate, request: Request, ctx: OpContext = Depends(op_context),
                 conn: Conn = Depends(tenant_conn), idem: str | None = Depends(idempotency_key)) -> Any:  # fmt: skip
    return run_idempotent(
        conn,
        ctx,
        request,
        idem,
        body.model_dump(mode="json"),
        lambda: kernel.create_context_frame(conn, ctx, **body.model_dump()),
    )


@router.get("/context-frames/{frame_id}", response_model=m.ContextFrameOut, tags=["kernel"])
def get_frame(frame_id: UUID, ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:
    return kernel.get_context_frame(conn, ctx, frame_id)


@router.post("/entities", response_model=m.EntityOut, status_code=201, tags=["kernel"])
def create_entity(body: m.EntityCreate, request: Request, response: Response, ctx: OpContext = Depends(op_context),
                  conn: Conn = Depends(tenant_conn), idem: str | None = Depends(idempotency_key)) -> Any:  # fmt: skip
    out = run_idempotent(
        conn,
        ctx,
        request,
        idem,
        body.model_dump(mode="json"),
        lambda: kernel.create_entity(conn, ctx, idempotency_key=idem, **body.model_dump()),
    )
    response.headers["ETag"] = f'"{out["version"]}"'
    return out


@router.get("/entities", response_model=m.Page[m.EntityOut], tags=["kernel"])
def list_entities(entity_type: str | None = None, limit: int = Query(50, ge=1, le=200),
                  cursor: UUID | None = None, order: str = Query("asc", pattern="^(asc|desc)$"),
                  ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    items = kernel.list_entities(conn, ctx, entity_type=entity_type, limit=limit, after=cursor, order=order)
    return {"items": items, "next_cursor": str(items[-1]["entity_id"]) if len(items) == limit else None}


@router.get("/entities/{entity_id}", response_model=m.EntityOut, tags=["kernel"])
def get_entity(entity_id: UUID, response: Response, ctx: OpContext = Depends(op_context),
               conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    row = kernel.get_entity(conn, ctx, entity_id)
    response.headers["ETag"] = f'"{row["version"]}"'
    return row


@router.patch("/entities/{entity_id}", response_model=m.EntityOut, tags=["kernel"],
              summary="Alteração material com concorrência otimista (If-Match obrigatório)")  # fmt: skip
def patch_entity(entity_id: UUID, body: m.EntityPatch, request: Request, response: Response,
                 if_match: str | None = Header(default=None), ctx: OpContext = Depends(op_context),
                 conn: Conn = Depends(tenant_conn), idem: str | None = Depends(idempotency_key)) -> Any:  # fmt: skip
    if not if_match:
        raise PreconditionFailed(
            "Cabeçalho If-Match (versão/ETag) obrigatório.", code="WE-KRN-428", status=428
        )
    try:
        expected = int(if_match.strip('W/"'))
    except ValueError as exc:
        raise ValidationFailed("If-Match inválido.") from exc
    data = body.model_dump(exclude_unset=True)
    frame = data.pop("context_frame_id", None)
    out = run_idempotent(
        conn, ctx, request, idem, {**body.model_dump(mode="json", exclude_unset=True), "if_match": expected},
        lambda: kernel.update_entity(conn, ctx, entity_id, expected_version=expected, changes=data,
                                     context_frame_id=frame, idempotency_key=idem),
        status_code=200)  # fmt: skip
    response.headers["ETag"] = f'"{out["version"]}"'
    return out


@router.post("/entities/{entity_id}/roles", response_model=m.RoleOut, status_code=201, tags=["kernel"])
def assign_role(entity_id: UUID, body: m.RoleCreate, ctx: OpContext = Depends(op_context),
                conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    return kernel.assign_role(conn, ctx, entity_id, **body.model_dump())


@router.post("/relations", response_model=m.RelationOut, status_code=201, tags=["kernel"])
def create_relation(body: m.RelationCreate, ctx: OpContext = Depends(op_context),
                    conn: Conn = Depends(tenant_conn)) -> Any:  # fmt: skip
    return kernel.create_relation(conn, ctx, **body.model_dump())


@router.get("/entities/{entity_id}/relations", response_model=m.Page[m.RelationOut], tags=["kernel"])
def list_relations(
    entity_id: UUID, ctx: OpContext = Depends(op_context), conn: Conn = Depends(tenant_conn)
) -> Any:
    return {"items": kernel.list_relations(conn, ctx, entity_id)}
