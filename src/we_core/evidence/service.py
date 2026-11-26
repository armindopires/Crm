"""Evidence Engine: receção validada, SHA-256 no servidor, armazenamento imutável e cadeia de custódia."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb

from we_core.audit import log as audit
from we_core.common import sha256_hex, utcnow, uuid7
from we_core.context import OpContext
from we_core.db import Conn
from we_core.errors import NotFound, ValidationFailed
from we_core.events.store import EventDraft, append
from we_core.evidence.storage import ObjectStorage
from we_core.identity.authz import Resource, require

ALLOWED_MEDIA = {
    "application/pdf": [b"%PDF-"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "application/json": None,
    "text/plain": None,
    "text/csv": None,
    "application/xml": None,
}
LINK_TARGETS = {"entity", "event", "workflow_instance", "obligation", "decision", "communication", "signal",
                "opportunity"}  # fmt: skip


def safe_filename(name: str | None) -> str:
    base = (name or "evidencia").replace("\\", "/").rsplit("/", 1)[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._") or "evidencia"
    return base[:120]


def sniff(media_type: str, data: bytes) -> None:
    if media_type not in ALLOWED_MEDIA:
        raise ValidationFailed(f"Tipo MIME não permitido: {media_type}", code="WE-EVD-MIME")
    magics = ALLOWED_MEDIA[media_type]
    if magics is not None and not any(data.startswith(m) for m in magics):
        raise ValidationFailed("O conteúdo não corresponde ao tipo MIME declarado.", code="WE-EVD-MIME")
    if magics is None:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationFailed("Conteúdo textual não é UTF-8 válido.", code="WE-EVD-MIME") from exc
        if b"\x00" in data:
            raise ValidationFailed("Conteúdo textual contém bytes nulos.", code="WE-EVD-MIME")


def storage_key(tenant_id: UUID, sha256: str) -> str:
    return f"tenants/{tenant_id}/sha256/{sha256[:2]}/{sha256}"


def register(
    conn: Conn,
    ctx: OpContext,
    storage: ObjectStorage,
    *,
    data: bytes,
    filename: str | None,
    media_type: str,
    classification: str,
    source: str,
    max_bytes: int,
    organization_id: UUID | None = None,
    retention_class: str = "NAO_INDICADO",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    require(
        conn,
        ctx.principal,
        "evidence:write",
        Resource("evidence", classification=classification, organization_id=organization_id),
        ctx.purpose,
    )
    if len(data) == 0:
        raise ValidationFailed("Evidência vazia.", code="WE-EVD-EMPTY")
    if len(data) > max_bytes:
        raise ValidationFailed(f"Evidência excede o limite de {max_bytes} bytes.", code="WE-EVD-SIZE")
    sniff(media_type, data)
    digest = hashlib.sha256(data).hexdigest()
    key = storage_key(ctx.tenant_id, digest)
    version = None
    if not storage.exists(key):
        version = storage.put(key, data, media_type, digest)
    evidence_id = uuid7()
    row = conn.execute(
        """INSERT INTO evidence.evidence (evidence_id, tenant_id, organization_id, sha256, size_bytes, media_type,
             filename_safe, storage_bucket, storage_key, storage_version, classification, retention_class, source,
             uploaded_by, uploaded_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
        (evidence_id, ctx.tenant_id, organization_id, digest, len(data), media_type, safe_filename(filename),
         storage.bucket, key, version, classification, retention_class, source, ctx.principal.actor_id, utcnow()),
    ).fetchone()  # fmt: skip
    assert row is not None
    conn.execute(
        "INSERT INTO evidence.custody_events (custody_event_id, tenant_id, evidence_id, action, actor_id, "
        "sha256_observed, details) VALUES (%s,%s,%s,'uploaded',%s,%s,%s)",
        (
            uuid7(),
            ctx.tenant_id,
            evidence_id,
            ctx.principal.actor_id,
            digest,
            Jsonb({"size_bytes": len(data)}),
        ),
    )
    ev = append(conn, ctx, EventDraft(
        event_type="evidence.evidence_registered", aggregate_type="evidence", aggregate_id=evidence_id,
        expected_version=0, organization_id=organization_id, classification=classification,
        idempotency_key=idempotency_key,
        payload={"sha256": digest, "size_bytes": len(data), "media_type": media_type,
                 "classification": classification, "storage_key_hash": sha256_hex(key)},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="evidence.register",
        resource_type="evidence",
        resource_id=evidence_id,
        outcome="succeeded",
        details={"sha256": digest, "event_id": str(ev.event["event_id"])},
    )
    return dict(row)


def get(conn: Conn, ctx: OpContext, evidence_id: UUID) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM evidence.evidence WHERE evidence_id = %s", (evidence_id,)).fetchone()
    if not row:
        raise NotFound("Evidência não encontrada.")
    require(
        conn,
        ctx.principal,
        "evidence:read",
        Resource("evidence", evidence_id, row["classification"], row["organization_id"]),
        ctx.purpose,
    )
    return dict(row)


def link(conn: Conn, ctx: OpContext, evidence_id: UUID, target_type: str, target_id: UUID,
         link_type: str = "supports", *, as_reference: bool = False) -> dict[str, Any]:  # fmt: skip
    """Liga evidência a um alvo. `as_reference=True` (ex.: proposta de decisão) exige só leitura da evidência."""
    if target_type not in LINK_TARGETS:
        raise ValidationFailed(f"Tipo de alvo inválido: {target_type}")
    ev = get(conn, ctx, evidence_id)
    if not as_reference:
        require(
            conn,
            ctx.principal,
            "evidence:write",
            Resource("evidence", evidence_id, ev["classification"], ev["organization_id"]),
        )
    row = conn.execute(
        """INSERT INTO evidence.links (link_id, tenant_id, evidence_id, target_type, target_id, link_type, created_by)
           VALUES (%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (tenant_id, evidence_id, target_type, target_id, link_type) DO NOTHING RETURNING *""",
        (uuid7(), ctx.tenant_id, evidence_id, target_type, target_id, link_type, ctx.principal.actor_id),
    ).fetchone()
    if row:
        conn.execute(
            "INSERT INTO evidence.custody_events (custody_event_id, tenant_id, evidence_id, action, actor_id, details)"
            " VALUES (%s,%s,%s,'linked',%s,%s)",
            (uuid7(), ctx.tenant_id, evidence_id, ctx.principal.actor_id,
             Jsonb({"target_type": target_type, "target_id": str(target_id)})),
        )  # fmt: skip
        append(conn, ctx, EventDraft(
            event_type="evidence.evidence_linked", classification=ev["classification"], aggregate_type="evidence", aggregate_id=evidence_id,
            payload={"target_type": target_type, "target_id": target_id, "link_type": link_type},
        ))  # fmt: skip
    return {
        "evidence_id": evidence_id,
        "target_type": target_type,
        "target_id": target_id,
        "link_type": link_type,
    }


def verify(conn: Conn, ctx: OpContext, storage: ObjectStorage, evidence_id: UUID) -> dict[str, Any]:
    ev = get(conn, ctx, evidence_id)
    require(
        conn,
        ctx.principal,
        "evidence:verify",
        Resource("evidence", evidence_id, ev["classification"], ev["organization_id"]),
    )
    data = storage.get(ev["storage_key"])
    observed = hashlib.sha256(data).hexdigest() if data is not None else None
    result = "missing" if data is None else ("ok" if observed == ev["sha256"] else "mismatch")
    conn.execute(
        "INSERT INTO evidence.custody_events (custody_event_id, tenant_id, evidence_id, action, actor_id, "
        "sha256_observed, details) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (uuid7(), ctx.tenant_id, evidence_id, "verified" if result == "ok" else "verification_failed",
         ctx.principal.actor_id, observed, Jsonb({"result": result})),
    )  # fmt: skip
    append(conn, ctx, EventDraft(
        event_type="evidence.integrity_verified", classification=ev["classification"], aggregate_type="evidence", aggregate_id=evidence_id,
        payload={"sha256_expected": ev["sha256"], "sha256_observed": observed, "result": result},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="evidence.verify",
        resource_type="evidence",
        resource_id=evidence_id,
        outcome="succeeded" if result == "ok" else "failed",
        details={"result": result},
    )
    return {"evidence_id": evidence_id, "sha256_expected": ev["sha256"], "sha256_observed": observed,
            "result": result, "valid": result == "ok"}  # fmt: skip


def custody(conn: Conn, ctx: OpContext, evidence_id: UUID) -> list[dict[str, Any]]:
    get(conn, ctx, evidence_id)
    return [dict(r) for r in conn.execute(
        "SELECT action, actor_id, occurred_at, sha256_observed, details FROM evidence.custody_events "
        "WHERE evidence_id = %s ORDER BY occurred_at", (evidence_id,)).fetchall()]  # fmt: skip
