"""Dependências da API: autenticação OIDC, contexto de tenant, rate limiting e idempotência HTTP."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import Depends, Header, Request
from psycopg import errors as pg_errors
from psycopg.types.json import Jsonb

from we_core.common import canonical_json, sha256_hex, to_jsonable, uuid7
from we_core.config import Settings
from we_core.context import OpContext
from we_core.db import Conn, Database
from we_core.errors import Conflict, TooManyRequests, Unauthenticated, ValidationFailed
from we_core.evidence.storage import ObjectStorage
from we_core.identity.oidc import TokenVerifier
from we_core.identity.principal import resolve_principal
from we_core.observability import tenant_var


@dataclass
class AppState:
    settings: Settings
    db: Database
    storage: ObjectStorage
    verifier: TokenVerifier
    redis: Any | None


def state(request: Request) -> AppState:
    return request.app.state.we  # type: ignore[no-any-return]


def _rate_limit(st: AppState, key: str) -> None:
    if st.redis is None:
        return
    window = int(time.time() // 60)
    rk = f"we:rl:{key}:{window}"
    try:
        n = st.redis.incr(rk)
        if n == 1:
            st.redis.expire(rk, 70)
    except Exception:  # noqa: BLE001 - Redis indisponível: fail-open documentado (ADR-0009)
        return
    if n > st.settings.rate_limit_per_minute:
        raise TooManyRequests("Limite de pedidos por minuto excedido para este tenant.")


def op_context(
    request: Request,
    authorization: str | None = Header(default=None),
    x_we_purpose: str | None = Header(default=None, description="Finalidade declarada do acesso (ABAC)"),
) -> OpContext:
    st = state(request)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthenticated("Cabeçalho Authorization Bearer em falta.")
    claims = st.verifier.verify(authorization[7:].strip())
    principal = resolve_principal(st.db, st.settings, claims)
    _rate_limit(st, str(principal.tenant_id or f"platform:{principal.subject}"))
    ctx = OpContext(
        principal=principal,
        correlation_id=request.state.correlation_id,
        trace_id=getattr(request.state, "trace_id", None),
        purpose=x_we_purpose,
        origin=request.client.host if request.client else None,
    )
    request.state.ctx = ctx
    tenant_var.set(str(principal.tenant_id) if principal.tenant_id else None)
    return ctx


def tenant_conn(request: Request, ctx: OpContext = Depends(op_context)) -> Iterator[Conn]:
    """Uma transação por pedido, com contexto de tenant (RLS). COMMIT no fim; ROLLBACK em erro."""
    if ctx.principal.tenant_id is None:
        raise Unauthenticated("Este recurso exige um token com tenant.", code="WE-AUTH-005")
    with state(request).db.tenant_tx(ctx.principal.tenant_id) as conn:
        yield conn


def idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str | None:
    if idempotency_key is not None and not (8 <= len(idempotency_key) <= 200):
        raise ValidationFailed("Idempotency-Key tem de ter entre 8 e 200 caracteres.", code="WE-IDEM-422")
    return idempotency_key


def run_idempotent(conn: Conn, ctx: OpContext, request: Request, key: str | None, body: Any,
                   fn: Callable[[], Any], status_code: int = 201) -> Any:  # fmt: skip
    """Mesma chave + mesmo pedido → mesma resposta, sem segundo efeito. Pedido diferente → 409."""
    if key is None:
        return fn()
    req_hash = sha256_hex(
        canonical_json({"m": request.method, "p": request.url.path, "b": to_jsonable(body)})
    )
    prev = conn.execute("SELECT * FROM api.idempotency_keys WHERE idem_key = %s", (key,)).fetchone()
    if prev:
        if prev["request_hash"] != req_hash:
            raise Conflict("Idempotency-Key reutilizada com um pedido diferente.", code="WE-IDEM-409")
        request.state.idempotent_replay = True
        return prev["response_body"]
    result = fn()
    payload = to_jsonable(result)
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO api.idempotency_keys (tenant_id, idem_key, method, path, request_hash, status_code, "
                "response_body) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (ctx.tenant_id, key, request.method, request.url.path, req_hash, status_code, Jsonb(payload)),
            )
    except pg_errors.UniqueViolation as exc:
        raise Conflict("Pedido concorrente com a mesma Idempotency-Key; repita o pedido.",
                       code="WE-IDEM-RACE") from exc  # fmt: skip
    return payload


def new_correlation(raw: str | None) -> UUID:
    if raw:
        try:
            return UUID(raw)
        except ValueError:
            pass
    return uuid7()
