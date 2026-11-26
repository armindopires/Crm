"""Erros de domínio com código estável e mensagem PT-PT (mapeados para application/problem+json)."""

from __future__ import annotations

from typing import Any


class WEError(Exception):
    status: int = 400
    code: str = "WE-GEN-000"
    title: str = "Pedido inválido"

    def __init__(
        self,
        detail: str,
        *,
        code: str | None = None,
        status: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        if code:
            self.code = code
        if status:
            self.status = status
        self.extra = extra or {}


class NotFound(WEError):
    status, code, title = 404, "WE-GEN-404", "Recurso não encontrado"


class Unauthenticated(WEError):
    status, code, title = 401, "WE-AUTH-001", "Autenticação necessária"


class Forbidden(WEError):
    status, code, title = 403, "WE-AUTH-003", "Acesso negado"


class Conflict(WEError):
    status, code, title = 409, "WE-GEN-409", "Conflito de estado"


class ConcurrencyConflict(Conflict):
    code, title = "WE-EVT-409", "Conflito de concorrência otimista"


class PreconditionFailed(WEError):
    status, code, title = 412, "WE-GEN-412", "Pré-condição falhou"


class ValidationFailed(WEError):
    status, code, title = 422, "WE-VAL-422", "Dados inválidos"


class HumanApprovalRequired(WEError):
    status, code, title = 409, "WE-GOV-HITL", "Aprovação humana obrigatória"


class TooManyRequests(WEError):
    status, code, title = 429, "WE-RATE-429", "Limite de pedidos excedido"


class DependencyUnavailable(WEError):
    status, code, title = 503, "WE-DEP-503", "Dependência indisponível"
