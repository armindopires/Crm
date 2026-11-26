"""Contexto operacional de cada pedido: quem (principal), porquê (finalidade) e correlação."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from we_core.common import CLASSIFICATIONS, uuid7


@dataclass(frozen=True)
class Principal:
    subject: str
    actor_id: UUID | None
    tenant_id: UUID | None
    actor_type: str  # human | service | ai_agent | system
    roles: frozenset[str] = frozenset()
    org_scope: frozenset[UUID] | None = None  # None = todo o tenant
    clearance: str = "internal"
    platform_roles: frozenset[str] = frozenset()

    def clearance_rank(self) -> int:
        return CLASSIFICATIONS.index(self.clearance)


SYSTEM = Principal(subject="system:we", actor_id=None, tenant_id=None, actor_type="system")


@dataclass
class OpContext:
    principal: Principal
    correlation_id: UUID = field(default_factory=uuid7)
    trace_id: str | None = None
    causation_id: UUID | None = None
    purpose: str | None = None
    origin: str | None = None

    @property
    def tenant_id(self) -> UUID:
        if self.principal.tenant_id is None:
            raise RuntimeError("operação de tenant sem tenant no contexto")
        return self.principal.tenant_id
