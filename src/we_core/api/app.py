"""Aplicação FastAPI da WE (API-first). Contrato exportado para contracts/openapi/we-api.v1.json."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from psycopg import errors as pg_errors

from we_core import __name__ as _pkg
from we_core.api.deps import AppState, new_correlation
from we_core.api.models import HealthOut
from we_core.api.routers import core, operations
from we_core.audit import log as audit
from we_core.config import Settings, get_settings
from we_core.context import OpContext
from we_core.db import Database
from we_core.errors import WEError
from we_core.events.registry import get_registry
from we_core.evidence.storage import ObjectStorage, S3Storage
from we_core.identity.oidc import TokenVerifier
from we_core.observability import correlation_var, metrics, setup_logging, setup_tracing

VERSION = "0.1.0"
log = logging.getLogger("we.api")
PROBLEM = "application/problem+json"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _problem(request: Request, status: int, code: str, title: str, detail: str,
             extra: dict[str, Any] | None = None) -> JSONResponse:  # fmt: skip
    body = {"type": f"https://errors.we.local/{code}", "title": title, "status": status, "detail": detail,
            "code": code, "correlation_id": str(getattr(request.state, "correlation_id", "")),
            "instance": request.url.path, **(extra or {})}  # fmt: skip
    return JSONResponse(body, status_code=status, media_type=PROBLEM)


def _audit_denial(request: Request, exc: WEError) -> None:
    ctx: OpContext | None = getattr(request.state, "ctx", None)
    if ctx is None or ctx.principal.tenant_id is None:
        return
    try:
        with request.app.state.we.db.tenant_tx(ctx.principal.tenant_id) as conn:
            audit.record(conn, ctx, action=f"http.{request.method.lower()}", resource_type="http",
                         resource_id=request.url.path, outcome="denied", reason=exc.detail,
                         policy_refs=[str(p) for p in exc.extra.get("policy_refs", [])],
                         details={"code": exc.code})  # fmt: skip
    except Exception:
        log.exception("falha a auditar negação")


def create_app(settings: Settings | None = None, storage: ObjectStorage | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.service_name, settings.log_level)
    setup_tracing(settings.service_name, settings.otel_exporter_otlp_endpoint)
    get_registry()  # falha cedo se algum schema for inválido

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.dsn("app"), settings.pg_pool_min, settings.pg_pool_max)
        db.open()
        store = storage or S3Storage(settings)
        try:
            store.ensure_bucket()
        except Exception:  # noqa: BLE001 - readiness reporta o problema
            log.warning("armazenamento de objetos indisponível no arranque")
        redis_client = None
        try:
            import redis

            redis_client = redis.Redis.from_url(settings.redis_url,
                                                password=settings.redis_password.get_secret_value() or None,
                                                socket_timeout=0.5, socket_connect_timeout=0.5)  # fmt: skip
        except Exception:  # noqa: BLE001
            redis_client = None
        app.state.we = AppState(settings, db, store, TokenVerifier(settings), redis_client)
        yield
        db.close()

    app = FastAPI(
        title="Wolf Enterprise API",
        version=VERSION,
        description="API fundacional da WE — Event Store, Evidence, Governance, Kernel cognitivo. "
        "Erros em application/problem+json com código estável e mensagem PT-PT.",
        lifespan=lifespan,
        openapi_url="/openapi.json",
        docs_url="/docs" if settings.env != "production" else None,
        redoc_url=None,
    )

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore[import-not-found]

        FastAPIInstrumentor.instrument_app(app)
    except ImportError:
        pass

    @app.middleware("http")
    async def correlation_mw(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        cid = new_correlation(request.headers.get("X-Correlation-ID"))
        request.state.correlation_id = cid
        request.state.trace_id = request.headers.get("traceparent")
        token = correlation_var.set(str(cid))
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            correlation_var.reset(token)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        metrics.http_requests.labels(request.method, path, str(response.status_code)).inc()
        metrics.http_latency.labels(request.method, path).observe(time.perf_counter() - start)
        response.headers["X-Correlation-ID"] = str(cid)
        if getattr(request.state, "idempotent_replay", False):
            response.headers["Idempotent-Replayed"] = "true"
        for k, v in SECURITY_HEADERS.items():
            response.headers.setdefault(k, v)
        if request.url.path.startswith("/docs"):
            del response.headers["Content-Security-Policy"]
        return response

    @app.exception_handler(WEError)
    async def we_error(request: Request, exc: WEError) -> JSONResponse:
        if exc.status == 403 or exc.code.startswith("WE-GOV-"):
            metrics.policy_denials.labels(exc.code).inc()
            _audit_denial(request, exc)
        extra = {
            k: v for k, v in exc.extra.items() if k in ("current_version", "policy_refs", "status", "action")
        }
        return _problem(request, exc.status, exc.code, exc.title, exc.detail, extra)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errs = [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()[:10]]
        return _problem(request, 422, "WE-VAL-422", "Dados inválidos", "O pedido não respeita o contrato.",
                        {"errors": errs})  # fmt: skip

    @app.exception_handler(pg_errors.InsufficientPrivilege)
    async def pg_priv(request: Request, exc: pg_errors.InsufficientPrivilege) -> JSONResponse:
        log.warning("privilégio insuficiente: %s", str(exc).splitlines()[0])
        return _problem(request, 403, "WE-DB-PRIV", "Operação não permitida",
                        "A operação foi recusada pela base de dados (append-only/RLS).")  # fmt: skip

    @app.exception_handler(pg_errors.ForeignKeyViolation)
    async def pg_fk(request: Request, exc: pg_errors.ForeignKeyViolation) -> JSONResponse:
        return _problem(request, 422, "WE-DB-REF", "Referência inválida",
                        "Uma das referências não existe neste tenant.")  # fmt: skip

    @app.exception_handler(pg_errors.RaiseException)
    async def pg_raise(request: Request, exc: pg_errors.RaiseException) -> JSONResponse:
        msg = str(exc).splitlines()[0]
        return _problem(request, 409, msg.split(":")[0] if msg.startswith("WE-") else "WE-DB-RULE",
                        "Regra de integridade violada", msg)  # fmt: skip

    @app.exception_handler(pg_errors.UniqueViolation)
    async def pg_unique(request: Request, exc: pg_errors.UniqueViolation) -> JSONResponse:
        return _problem(
            request, 409, "WE-DB-UNIQUE", "Conflito", "Já existe um registo com esses identificadores."
        )

    @app.get("/health/live", response_model=HealthOut, tags=["system"])
    def live() -> dict[str, Any]:
        return {"status": "ok", "checks": {}, "version": VERSION}

    @app.get("/health/ready", response_model=HealthOut, tags=["system"],
             responses={503: {"model": HealthOut}})  # fmt: skip
    def ready(request: Request, response: Response) -> dict[str, Any]:
        st: AppState = request.app.state.we
        checks: dict[str, str] = {}
        try:
            checks["postgres"] = "ok" if st.db.ping() else "fail"
        except Exception:  # noqa: BLE001
            checks["postgres"] = "fail"
        checks["object_storage"] = "ok" if st.storage.ping() else "fail"
        try:
            checks["redis"] = "ok" if st.redis is not None and st.redis.ping() else "degraded"
        except Exception:  # noqa: BLE001
            checks["redis"] = "degraded"  # rate limiting em fail-open
        status = (
            "fail" if "fail" in checks.values() else ("degraded" if "degraded" in checks.values() else "ok")
        )
        if status == "fail":
            response.status_code = 503
        return {"status": status, "checks": checks, "version": VERSION}

    @app.get("/metrics", include_in_schema=False)
    def prom() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    app.include_router(core.router)
    app.include_router(operations.router)
    _ = _pkg
    return app
