"""Cognitive Kernel: ENTITY, ROLE, RELATION e CONTEXT_FRAME.

Cada alteração material grava estado + EVENT + AUDIT_LOG na mesma transação.
Context frames são snapshots imutáveis: alterar o contexto cria uma nova versão.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from we_core.audit import log as audit
from we_core.common import canonical_json, sha256_hex, uuid7
from we_core.context import OpContext
from we_core.db import Conn
from we_core.errors import NotFound, PreconditionFailed, ValidationFailed
from we_core.events.store import EventDraft, append
from we_core.identity.authz import Resource, require

FORBIDDEN_ATTRIBUTE_KEYS = ("password", "passwd", "pwd", "senha", "secret", "token", "cookie", "private_key",
                            "api_key", "certificado", "certificate")  # fmt: skip


def _check_attributes(attrs: dict[str, Any]) -> None:
    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if any(f in k.lower() for f in FORBIDDEN_ATTRIBUTE_KEYS):
                    raise ValidationFailed(f"Atributo proibido (segredo): {path}{k}", code="WE-KRN-SECRET")
                walk(v, f"{path}{k}.")
        elif isinstance(obj, list):
            for i in obj:
                walk(i, path)

    walk(attrs, "")
    if len(canonical_json(attrs)) > 64_000:
        raise ValidationFailed("Atributos excedem 64 KB.")


def _get_entity_row(conn: Conn, entity_id: UUID) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM kernel.entities WHERE entity_id = %s", (entity_id,)).fetchone()
    if not row:
        raise NotFound("Entidade não encontrada.")
    return dict(row)


def create_context_frame(
    conn: Conn,
    ctx: OpContext,
    *,
    frame_key: str,
    purpose: str,
    snapshot: dict[str, Any],
    jurisdiction: str = "PT",
    organization_id: UUID | None = None,
    valid_from: datetime | None = None,
    valid_to: datetime | None = None,
) -> dict[str, Any]:
    require(conn, ctx.principal, "context:write", Resource("context_frame", organization_id=organization_id))
    _check_attributes(snapshot)
    prev = conn.execute(
        "SELECT context_frame_id, version FROM kernel.context_frames WHERE frame_key = %s "
        "ORDER BY version DESC LIMIT 1", (frame_key,)).fetchone()  # fmt: skip
    version = int(prev["version"]) + 1 if prev else 1
    frame_id = uuid7()
    snap_hash = sha256_hex(canonical_json(snapshot))
    row = conn.execute(
        """INSERT INTO kernel.context_frames (context_frame_id, tenant_id, organization_id, frame_key, version,
             purpose, jurisdiction, valid_from, valid_to, snapshot, snapshot_hash, supersedes_id, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (frame_id, ctx.tenant_id, organization_id, frame_key, version, purpose, jurisdiction, valid_from, valid_to,
         Jsonb(snapshot), snap_hash, prev["context_frame_id"] if prev else None, ctx.principal.actor_id),
    ).fetchone()  # fmt: skip
    assert row is not None
    append(conn, ctx, EventDraft(
        event_type="kernel.context_frame_created", aggregate_type="context_frame", aggregate_id=frame_id,
        expected_version=0, organization_id=organization_id, context_frame_id=frame_id,
        payload={"frame_key": frame_key, "version": version, "purpose": purpose, "jurisdiction": jurisdiction,
                 "snapshot_hash": snap_hash, "supersedes_id": prev["context_frame_id"] if prev else None},
    ))  # fmt: skip
    return dict(row)


def get_context_frame(conn: Conn, ctx: OpContext, frame_id: UUID) -> dict[str, Any]:
    require(conn, ctx.principal, "context:read", Resource("context_frame", frame_id))
    row = conn.execute(
        "SELECT * FROM kernel.context_frames WHERE context_frame_id = %s", (frame_id,)
    ).fetchone()
    if not row:
        raise NotFound("Context frame não encontrado.")
    return dict(row)


def create_entity(
    conn: Conn,
    ctx: OpContext,
    *,
    entity_type: str,
    display_name: str,
    classification: str,
    attributes: dict[str, Any],
    organization_id: UUID | None,
    context_frame_id: UUID | None,
    idempotency_key: str | None = None,
    source_ref: str | None = None,
) -> dict[str, Any]:
    require(
        conn,
        ctx.principal,
        "entity:write",
        Resource("entity", classification=classification, organization_id=organization_id),
        ctx.purpose,
    )
    _check_attributes(attributes)
    entity_id = uuid7()
    row = conn.execute(
        """INSERT INTO kernel.entities (entity_id, tenant_id, organization_id, entity_type, display_name,
             classification, attributes) VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (
            entity_id,
            ctx.tenant_id,
            organization_id,
            entity_type,
            display_name,
            classification,
            Jsonb(attributes),
        ),
    ).fetchone()
    assert row is not None
    ev = append(conn, ctx, EventDraft(
        event_type="kernel.entity_created", aggregate_type="entity", aggregate_id=entity_id, expected_version=0,
        organization_id=organization_id, context_frame_id=context_frame_id, classification=classification,
        idempotency_key=idempotency_key,
        payload={"entity_type": entity_type, "classification": classification, "organization_id": organization_id,
                 "attribute_keys": sorted(attributes), "source_ref": source_ref},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="entity.create",
        resource_type="entity",
        resource_id=entity_id,
        outcome="succeeded",
        context_frame_id=context_frame_id,
        details={"event_id": str(ev.event["event_id"])},
    )
    return {**dict(row), "event_id": ev.event["event_id"]}


def get_entity(conn: Conn, ctx: OpContext, entity_id: UUID) -> dict[str, Any]:
    row = _get_entity_row(conn, entity_id)
    require(
        conn,
        ctx.principal,
        "entity:read",
        Resource("entity", entity_id, row["classification"], row["organization_id"]),
        ctx.purpose,
    )
    return row


def list_entities(conn: Conn, ctx: OpContext, *, entity_type: str | None, limit: int, after: UUID | None,
                  order: str = "asc") -> list[dict[str, Any]]:  # fmt: skip
    require(conn, ctx.principal, "entity:read", Resource("entity"))
    clauses: list[str] = ["true"]
    params: list[object] = []
    if entity_type:
        clauses.append("entity_type = %s")
        params.append(entity_type)
    if after:
        clauses.append("entity_id > %s" if order == "asc" else "entity_id < %s")
        params.append(after)
    rank = ctx.principal.clearance_rank()
    clauses.append(
        "array_position(ARRAY['public','internal','confidential','restricted','secret'], "
        "classification) - 1 <= %s"
    )
    params.append(rank)
    if ctx.principal.org_scope is not None:
        clauses.append("(organization_id IS NULL OR organization_id = ANY(%s))")
        params.append(list(ctx.principal.org_scope))
    direction = "ASC" if order == "asc" else "DESC"
    sql = (
        f"SELECT * FROM kernel.entities WHERE {' AND '.join(clauses)} ORDER BY entity_id {direction} LIMIT %s"
    )
    return [dict(r) for r in conn.execute(sql.encode(), (*params, limit)).fetchall()]


def update_entity(conn: Conn, ctx: OpContext, entity_id: UUID, *, expected_version: int,
                  changes: dict[str, Any], context_frame_id: UUID | None,
                  idempotency_key: str | None = None) -> dict[str, Any]:  # fmt: skip
    row = conn.execute(
        "SELECT * FROM kernel.entities WHERE entity_id = %s FOR UPDATE", (entity_id,)
    ).fetchone()
    if not row:
        raise NotFound("Entidade não encontrada.")
    require(
        conn,
        ctx.principal,
        "entity:write",
        Resource("entity", entity_id, row["classification"], row["organization_id"]),
        ctx.purpose,
    )
    if row["version"] != expected_version:
        raise PreconditionFailed(
            f"A entidade está na versão {row['version']}; o pedido indicou {expected_version}.",
            code="WE-KRN-412", extra={"current_version": row["version"]})  # fmt: skip
    allowed = {"display_name", "attributes", "status", "classification"}
    bad = set(changes) - allowed
    if bad or not changes:
        raise ValidationFailed(f"Campos não alteráveis ou vazio: {sorted(bad)}")
    if "attributes" in changes:
        _check_attributes(changes["attributes"])
    new = {**row, **changes}
    updated = conn.execute(
        """UPDATE kernel.entities SET display_name = %s, attributes = %s, status = %s, classification = %s,
             version = version + 1, updated_at = now() WHERE entity_id = %s AND version = %s RETURNING *""",
        (new["display_name"], Jsonb(new["attributes"]), new["status"], new["classification"], entity_id,
         expected_version),
    ).fetchone()  # fmt: skip
    if not updated:
        raise PreconditionFailed("Alteração concorrente detetada.", code="WE-KRN-412")
    changed = [k for k in changes if k != "attributes" and changes[k] != row[k]]
    if "attributes" in changes:
        old_a, new_a = row["attributes"], changes["attributes"]
        changed += [
            f"attributes.{k}" for k in sorted(set(old_a) | set(new_a)) if old_a.get(k) != new_a.get(k)
        ]
    changed = sorted(changed)
    ev = append(conn, ctx, EventDraft(
        event_type="kernel.entity_updated", aggregate_type="entity", aggregate_id=entity_id,
        expected_version=expected_version, organization_id=row["organization_id"],
        context_frame_id=context_frame_id, classification=updated["classification"],
        idempotency_key=idempotency_key,
        payload={"changed_fields": changed, "new_version": updated["version"], "status": updated["status"],
                 "classification": updated["classification"]},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="entity.update",
        resource_type="entity",
        resource_id=entity_id,
        outcome="succeeded",
        context_frame_id=context_frame_id,
        details={"changed_fields": changed, "event_id": str(ev.event["event_id"])},
    )
    return {**dict(updated), "event_id": ev.event["event_id"]}


def assign_role(conn: Conn, ctx: OpContext, entity_id: UUID, *, role_type: str,
                organization_id: UUID | None) -> dict[str, Any]:  # fmt: skip
    ent = get_entity(conn, ctx, entity_id)
    require(
        conn,
        ctx.principal,
        "entity:write",
        Resource("entity", entity_id, ent["classification"], ent["organization_id"]),
    )
    role_id = uuid7()
    row = conn.execute(
        "INSERT INTO kernel.entity_roles (role_id, tenant_id, entity_id, role_type, organization_id) "
        "VALUES (%s,%s,%s,%s,%s) RETURNING *",
        (role_id, ctx.tenant_id, entity_id, role_type, organization_id),
    ).fetchone()
    assert row is not None
    append(conn, ctx, EventDraft(
        event_type="kernel.entity_role_assigned", aggregate_type="entity", aggregate_id=entity_id,
        organization_id=organization_id,
        payload={"role_id": role_id, "role_type": role_type, "organization_id": organization_id,
                 "valid_from": row["valid_from"]},
    ))  # fmt: skip
    return dict(row)


def create_relation(conn: Conn, ctx: OpContext, *, source_entity_id: UUID, target_entity_id: UUID,
                    relation_type: str, attributes: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    src = get_entity(conn, ctx, source_entity_id)
    get_entity(conn, ctx, target_entity_id)
    require(
        conn,
        ctx.principal,
        "entity:write",
        Resource("relation", classification=src["classification"], organization_id=src["organization_id"]),
    )
    _check_attributes(attributes)
    relation_id = uuid7()
    row = conn.execute(
        "INSERT INTO kernel.relations (relation_id, tenant_id, source_entity_id, target_entity_id, relation_type, "
        "attributes) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (relation_id, ctx.tenant_id, source_entity_id, target_entity_id, relation_type, Jsonb(attributes)),
    ).fetchone()
    assert row is not None
    append(conn, ctx, EventDraft(
        event_type="kernel.relation_created", aggregate_type="entity", aggregate_id=source_entity_id,
        payload={"relation_id": relation_id, "source_entity_id": source_entity_id,
                 "target_entity_id": target_entity_id, "relation_type": relation_type},
    ))  # fmt: skip
    return dict(row)


def list_relations(conn: Conn, ctx: OpContext, entity_id: UUID) -> list[dict[str, Any]]:
    get_entity(conn, ctx, entity_id)
    return [dict(r) for r in conn.execute(
        "SELECT * FROM kernel.relations WHERE source_entity_id = %s OR target_entity_id = %s ORDER BY created_at",
        (entity_id, entity_id)).fetchall()]  # fmt: skip
