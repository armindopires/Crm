"""Resolução de Principal a partir de claims validadas + estado de ator/membership na base de dados."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from we_core.config import Settings
from we_core.context import Principal
from we_core.db import Database
from we_core.errors import Forbidden, Unauthenticated


def resolve_principal(db: Database, settings: Settings, claims: dict[str, Any]) -> Principal:
    subject = str(claims["sub"])
    platform_roles = frozenset(claims.get(settings.oidc_platform_role_claim) or [])
    raw_tenant = claims.get(settings.oidc_tenant_claim)
    if not raw_tenant:
        if not platform_roles:
            raise Forbidden("Token sem tenant nem papel de plataforma.", code="WE-AUTH-005")
        return Principal(subject=subject, actor_id=None, tenant_id=None, actor_type="human",
                         platform_roles=platform_roles, clearance="internal")  # fmt: skip
    try:
        tenant_id = UUID(str(raw_tenant))
    except ValueError as exc:
        raise Unauthenticated("Claim de tenant inválida.", code="WE-AUTH-002") from exc

    with db.tenant_tx(tenant_id) as conn:
        actor = conn.execute(
            "SELECT actor_id, actor_type, clearance, status FROM iam.actors WHERE idp_subject = %s",
            (subject,),
        ).fetchone()
        if not actor or actor["status"] != "active":
            # Mesma resposta para tenant inexistente, ator inexistente ou desativado (sem enumeração).
            raise Forbidden("Sem acesso a este tenant.", code="WE-AUTH-006")
        memberships = conn.execute(
            """SELECT organization_id, roles FROM iam.memberships
               WHERE actor_id = %s AND valid_from <= now() AND (valid_to IS NULL OR valid_to > now())""",
            (actor["actor_id"],),
        ).fetchall()
    if not memberships:
        raise Forbidden("Sem acesso a este tenant.", code="WE-AUTH-006")
    roles: set[str] = set()
    orgs: set[UUID] = set()
    tenant_wide = False
    for m in memberships:
        roles.update(m["roles"])
        if m["organization_id"] is None:
            tenant_wide = True
        else:
            orgs.add(m["organization_id"])
    return Principal(
        subject=subject,
        actor_id=actor["actor_id"],
        tenant_id=tenant_id,
        actor_type=actor["actor_type"],
        roles=frozenset(roles),
        org_scope=None if tenant_wide else frozenset(orgs),
        clearance=actor["clearance"],
        platform_roles=platform_roles,
    )
