"""Autorização: RBAC (permissões estáveis) + ABAC (classificação, organização, finalidade, tipo de ator).

Deny-by-default. Políticas `deny` em iam.policies sobrepõem-se a qualquer permissão RBAC.
Cada decisão devolve as referências das políticas aplicadas, para auditoria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from we_core.common import CLASSIFICATIONS
from we_core.context import Principal
from we_core.db import Conn
from we_core.errors import Forbidden

READ_ALL = {
    "tenant:read", "org:read", "entity:read", "context:read", "event:read", "evidence:read",
    "decision:read", "signal:read", "opportunity:read", "audit:read", "source:read", "import:read",
    "policy:read", "workflow:read", "obligation:read", "knowledge:read",
}  # fmt: skip

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "tenant_admin": READ_ALL | {
        "org:write", "actor:write", "policy:write", "entity:write", "context:write", "evidence:write",
        "evidence:verify", "decision:propose", "decision:execute", "signal:write", "opportunity:write",
        "audit:verify", "event:verify", "projection:replay", "outbox:admin", "source:write", "import:write",
        "workflow:write", "obligation:write", "ai:invoke",
    },
    "operator": {
        "tenant:read", "org:read", "entity:read", "entity:write", "context:read", "context:write",
        "event:read", "evidence:read", "evidence:write", "evidence:verify", "decision:read", "decision:propose",
        "decision:execute", "signal:read", "signal:write", "opportunity:read", "opportunity:write",
        "source:read", "import:read", "import:write", "workflow:read", "workflow:write", "obligation:read",
        "knowledge:read", "ai:invoke",
    },
    "approver": {
        "tenant:read", "entity:read", "context:read", "event:read", "evidence:read", "evidence:verify",
        "decision:read", "decision:approve", "signal:read", "opportunity:read",
    },
    "auditor": READ_ALL | {"audit:verify", "event:verify", "evidence:verify"},
    "ai_agent": {"entity:read", "context:read", "evidence:read", "decision:propose", "ai:invoke", "signal:write", "knowledge:read"},
}  # fmt: skip

PLATFORM_ROLE_PERMISSIONS: dict[str, set[str]] = {"platform_admin": {"tenant:create", "platform:read"}}

# Atos que nunca podem ser praticados por IA, independentemente de papéis atribuídos.
HUMAN_ONLY = {"decision:approve", "policy:write", "actor:write", "outbox:admin"}


@dataclass
class Resource:
    resource_type: str
    resource_id: UUID | str | None = None
    classification: str = "internal"
    organization_id: UUID | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthzDecision:
    allowed: bool
    reason: str
    policy_refs: list[str]


def permissions_of(p: Principal) -> set[str]:
    perms: set[str] = set()
    for r in p.roles:
        perms |= ROLE_PERMISSIONS.get(r, set())
    for r in p.platform_roles:
        perms |= PLATFORM_ROLE_PERMISSIONS.get(r, set())
    return perms


def _matches(cond: dict[str, Any], p: Principal, res: Resource, purpose: str | None) -> bool:
    checks: list[bool] = []
    if "classification_in" in cond:
        checks.append(res.classification in cond["classification_in"])
    if "resource_type_in" in cond:
        checks.append(res.resource_type in cond["resource_type_in"])
    if "actor_type_in" in cond:
        checks.append(p.actor_type in cond["actor_type_in"])
    if "purpose_not_in" in cond:
        checks.append((purpose or "") not in cond["purpose_not_in"])
    if "organization_id_in" in cond:
        checks.append(str(res.organization_id) in {str(x) for x in cond["organization_id_in"]})
    return all(checks) if checks else True


def evaluate(
    conn: Conn | None, p: Principal, action: str, res: Resource, purpose: str | None = None
) -> AuthzDecision:
    refs: list[str] = [f"rbac:{action}"]
    if action not in permissions_of(p):
        return AuthzDecision(False, f"Sem permissão RBAC para {action}.", refs)
    if action in HUMAN_ONLY and p.actor_type != "human":
        return AuthzDecision(False, f"{action} exige ator humano.", [*refs, "hitl:human_only"])
    if CLASSIFICATIONS.index(res.classification) > p.clearance_rank():
        return AuthzDecision(False, "Classificação do recurso excede a habilitação do ator.",
                             [*refs, "abac:clearance"])  # fmt: skip
    refs.append("abac:clearance")
    if p.org_scope is not None and res.organization_id is not None and res.organization_id not in p.org_scope:
        return AuthzDecision(
            False, "Recurso fora do âmbito organizacional do ator.", [*refs, "abac:org_scope"]
        )
    refs.append("abac:org_scope")
    if conn is not None and p.tenant_id is not None:
        rows = conn.execute(
            """SELECT DISTINCT ON (name) policy_id, name, version, effect, actions, conditions
               FROM iam.policies WHERE status = 'active' ORDER BY name, version DESC"""
        ).fetchall()
        for row in rows:
            if row["effect"] != "deny":
                continue
            if action not in row["actions"] and "*" not in row["actions"]:
                continue
            if _matches(row["conditions"], p, res, purpose):
                ref = f"policy:{row['name']}@v{row['version']}"
                return AuthzDecision(
                    False, f"Negado pela política {row['name']} v{row['version']}.", [*refs, ref]
                )
            refs.append(f"policy:{row['name']}@v{row['version']}:not_applicable")
    return AuthzDecision(True, "Permitido.", refs)


def require(
    conn: Conn | None, p: Principal, action: str, res: Resource, purpose: str | None = None
) -> AuthzDecision:
    d = evaluate(conn, p, action, res, purpose)
    if not d.allowed:
        raise Forbidden(d.reason, code="WE-AUTH-003", extra={"policy_refs": d.policy_refs, "action": action})
    return d
