"""Platform & Tenancy + Identity & Access: tenants, organizações, atores, memberships e políticas."""

from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from we_core.audit import log as audit
from we_core.common import uuid7
from we_core.context import OpContext
from we_core.db import Conn, Database
from we_core.errors import Conflict, Forbidden, ValidationFailed
from we_core.events.store import EventDraft, append
from we_core.identity.authz import ROLE_PERMISSIONS, Resource, permissions_of, require

SUPPORTED_POLICY_CONDITIONS = {"classification_in", "resource_type_in", "actor_type_in", "purpose_not_in",
                               "organization_id_in"}  # fmt: skip


def create_tenant(db: Database, ctx: OpContext, *, slug: str, display_name: str, organization_name: str,
                  admin_subject: str, admin_display_name: str, is_synthetic: bool) -> dict[str, Any]:  # fmt: skip
    if "tenant:create" not in permissions_of(ctx.principal):
        raise Forbidden("Apenas administradores de plataforma criam tenants.", code="WE-AUTH-003")
    tenant_id, org_id, actor_id = uuid7(), uuid7(), uuid7()
    tctx = dataclasses.replace(ctx, principal=dataclasses.replace(ctx.principal, tenant_id=tenant_id))
    with db.tenant_tx(tenant_id, platform_scope=True) as conn:
        if conn.execute("SELECT 1 FROM platform.tenants WHERE slug = %s", (slug,)).fetchone():
            raise Conflict("Já existe um tenant com esse identificador.", code="WE-TEN-409")
        conn.execute(
            "INSERT INTO platform.tenants (tenant_id, slug, display_name, is_synthetic) VALUES (%s,%s,%s,%s)",
            (tenant_id, slug, display_name, is_synthetic),
        )
        conn.execute(
            "INSERT INTO platform.organizations (organization_id, tenant_id, name) VALUES (%s,%s,%s)",
            (org_id, tenant_id, organization_name),
        )
        conn.execute(
            "INSERT INTO iam.actors (actor_id, tenant_id, idp_subject, actor_type, display_name, clearance) "
            "VALUES (%s,%s,%s,'human',%s,'restricted')",
            (actor_id, tenant_id, admin_subject, admin_display_name),
        )
        conn.execute(
            "INSERT INTO iam.memberships (membership_id, tenant_id, actor_id, organization_id, roles) "
            "VALUES (%s,%s,%s,NULL,%s)",
            (uuid7(), tenant_id, actor_id, ["tenant_admin"]),
        )
        append(conn, tctx, EventDraft(
            event_type="platform.tenant_created", aggregate_type="tenant", aggregate_id=tenant_id,
            expected_version=0,
            payload={"slug": slug, "is_synthetic": is_synthetic, "initial_organization_id": org_id,
                     "initial_admin_actor_id": actor_id},
        ))  # fmt: skip
        audit.record(
            conn,
            tctx,
            action="tenant.create",
            resource_type="tenant",
            resource_id=tenant_id,
            outcome="succeeded",
            policy_refs=["platform:tenant:create"],
        )
    return {"tenant_id": tenant_id, "slug": slug, "display_name": display_name, "organization_id": org_id,
            "admin_actor_id": actor_id, "is_synthetic": is_synthetic}  # fmt: skip


def get_tenant(conn: Conn, ctx: OpContext) -> dict[str, Any]:
    require(conn, ctx.principal, "tenant:read", Resource("tenant", ctx.tenant_id))
    row = conn.execute("SELECT * FROM platform.tenants WHERE tenant_id = %s", (ctx.tenant_id,)).fetchone()
    assert row is not None
    return dict(row)


def list_organizations(conn: Conn, ctx: OpContext) -> list[dict[str, Any]]:
    require(conn, ctx.principal, "org:read", Resource("organization"))
    rows = conn.execute("SELECT * FROM platform.organizations ORDER BY created_at").fetchall()
    scope = ctx.principal.org_scope
    return [dict(r) for r in rows if scope is None or r["organization_id"] in scope]


def create_organization(conn: Conn, ctx: OpContext, *, name: str, legal_form: str | None,
                        tax_identifier: str | None) -> dict[str, Any]:  # fmt: skip
    require(conn, ctx.principal, "org:write", Resource("organization"))
    org_id = uuid7()
    row = conn.execute(
        "INSERT INTO platform.organizations (organization_id, tenant_id, name, legal_form, tax_identifier) "
        "VALUES (%s,%s,%s,%s,%s) RETURNING *",
        (org_id, ctx.tenant_id, name, legal_form, tax_identifier),
    ).fetchone()
    assert row is not None
    append(conn, ctx, EventDraft(event_type="platform.organization_created", aggregate_type="organization",
                                 aggregate_id=org_id, expected_version=0, organization_id=org_id,
                                 payload={"organization_id": org_id, "country_code": "PT"}))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="organization.create",
        resource_type="organization",
        resource_id=org_id,
        outcome="succeeded",
    )
    return dict(row)


def create_actor(conn: Conn, ctx: OpContext, *, idp_subject: str, actor_type: str, display_name: str,
                 clearance: str, roles: list[str], organization_id: UUID | None) -> dict[str, Any]:  # fmt: skip
    require(conn, ctx.principal, "actor:write", Resource("actor"))
    unknown = set(roles) - set(ROLE_PERMISSIONS)
    if unknown:
        raise ValidationFailed(f"Papéis desconhecidos: {sorted(unknown)}")
    if actor_type == "ai_agent" and set(roles) - {"ai_agent"}:
        raise ValidationFailed("Agentes de IA só podem ter o papel ai_agent.", code="WE-IAM-AI-ROLE")
    if conn.execute("SELECT 1 FROM iam.actors WHERE idp_subject = %s", (idp_subject,)).fetchone():
        raise Conflict("Já existe um ator com esse sujeito IdP neste tenant.", code="WE-IAM-409")
    actor_id = uuid7()
    row = conn.execute(
        "INSERT INTO iam.actors (actor_id, tenant_id, idp_subject, actor_type, display_name, clearance) "
        "VALUES (%s,%s,%s,%s,%s,%s) RETURNING actor_id, actor_type, display_name, clearance, status, created_at",
        (actor_id, ctx.tenant_id, idp_subject, actor_type, display_name, clearance),
    ).fetchone()
    assert row is not None
    conn.execute(
        "INSERT INTO iam.memberships (membership_id, tenant_id, actor_id, organization_id, roles) "
        "VALUES (%s,%s,%s,%s,%s)",
        (uuid7(), ctx.tenant_id, actor_id, organization_id, roles),
    )
    append(
        conn,
        ctx,
        EventDraft(
            event_type="iam.actor_created",
            aggregate_type="actor",
            aggregate_id=actor_id,
            expected_version=0,
            payload={"actor_type": actor_type, "clearance": clearance},
        ),
    )
    append(
        conn,
        ctx,
        EventDraft(
            event_type="iam.membership_granted",
            aggregate_type="actor",
            aggregate_id=actor_id,
            payload={"actor_id": actor_id, "organization_id": organization_id, "roles": roles},
        ),
    )
    audit.record(
        conn,
        ctx,
        action="actor.create",
        resource_type="actor",
        resource_id=actor_id,
        outcome="succeeded",
        details={"roles": roles, "actor_type": actor_type},
    )
    return {**dict(row), "roles": roles, "organization_id": organization_id}


def create_policy(conn: Conn, ctx: OpContext, *, name: str, effect: str, actions: list[str],
                  conditions: dict[str, Any], description: str | None) -> dict[str, Any]:  # fmt: skip
    require(conn, ctx.principal, "policy:write", Resource("policy"))
    unknown = set(conditions) - SUPPORTED_POLICY_CONDITIONS
    if unknown:
        raise ValidationFailed(f"Condições não suportadas: {sorted(unknown)}", code="WE-POL-COND")
    cur = conn.execute(
        "SELECT coalesce(max(version),0) AS v FROM iam.policies WHERE name = %s", (name,)
    ).fetchone()
    version = int(cur["v"]) + 1 if cur else 1
    policy_id = uuid7()
    row = conn.execute(
        "INSERT INTO iam.policies (policy_id, tenant_id, name, version, effect, actions, conditions, description, "
        "created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (policy_id, ctx.tenant_id, name, version, effect, actions, Jsonb(conditions), description,
         ctx.principal.actor_id),
    ).fetchone()  # fmt: skip
    assert row is not None
    append(
        conn,
        ctx,
        EventDraft(
            event_type="iam.policy_created",
            aggregate_type="policy",
            aggregate_id=policy_id,
            expected_version=0,
            payload={"name": name, "version": version, "effect": effect, "actions": actions},
        ),
    )
    audit.record(
        conn,
        ctx,
        action="policy.create",
        resource_type="policy",
        resource_id=policy_id,
        outcome="succeeded",
        policy_refs=[f"policy:{name}@v{version}"],
    )
    return dict(row)
