"""Importador seguro de depósitos JSON de conhecimento (prova de conceito da Fase 3).

1. calcula SHA-256 do depósito e do schema; regista a fonte (proveniência, autoridade);
2. valida o depósito contra o JSON Schema — se falhar, nada é importado (lote `failed`, quarentena);
3. cria KNOWLEDGE_NODEs por registo com JSON pointer de origem; segredos são descartados e campos
   pessoais/restritos excluídos do corpo, embeddings e índices;
4. reconcilia contagens e hash; lote → validated → reconciled; eventos + auditoria.
Os nós ficam `imported_unvalidated`: importar não é o mesmo que aceitar como verdade canónica.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from jsonschema import FormatChecker
from jsonschema.validators import validator_for
from psycopg.types.json import Jsonb

from we_core.audit import log as audit
from we_core.common import canonical_json, sha256_hex, uuid7
from we_core.config import Settings
from we_core.context import OpContext
from we_core.db import Conn, Database
from we_core.errors import ValidationFailed
from we_core.events.store import EventDraft, append
from we_core.identity.authz import Resource, require
from we_core.legacy import service as legacy

SECRET_KEYS = re.compile(r"(?i)(pass(word|wd)?|pwd|senha|secret|token|cookie|private[_-]?key|api[_-]?key|"
                         r"certificado|credencial|credential)")  # fmt: skip
PII_KEYS = re.compile(r"(?i)^(nif|nipc|niss|iban|nib|swift|bic|email|e_mail|telefone|telemovel|phone|mobile|"
                      r"morada|address|cc|bi|passaporte|data_nascimento|birth.*)$")  # fmt: skip
EMBEDDING_DIM = 256
EMBEDDING_MODEL = "we-featurehash-256-v1"  # não semântico; substituível (ADR-0011)


def embed(text: str) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    for tok in re.findall(r"\w+", text.lower()):
        h = int.from_bytes(hashlib.sha256(tok.encode()).digest()[:8], "big")
        vec[h % EMBEDDING_DIM] += 1.0 if (h >> 63) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def sanitize(obj: Any, pointer: str, excluded: list[str]) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            p = f"{pointer}/{k}"
            if SECRET_KEYS.search(k):
                excluded.append(f"secret:{p}")
                continue  # segredos nunca entram na WE
            if PII_KEYS.match(k):
                excluded.append(f"pii:{p}")
                out[k] = "[EXCLUIDO:pii]"
                continue
            out[k] = sanitize(v, p, excluded)
        return out
    if isinstance(obj, list):
        return [sanitize(v, f"{pointer}/{i}", excluded) for i, v in enumerate(obj)]
    return obj


def _records(deposit: Any) -> list[tuple[str, str, Any]]:
    """(colecção, json_pointer, registo)."""
    if isinstance(deposit, list):
        return [("root", f"/{i}", r) for i, r in enumerate(deposit)]
    if isinstance(deposit, dict):
        out: list[tuple[str, str, Any]] = []
        for k, v in deposit.items():
            if isinstance(v, list):
                out.extend((k, f"/{k}/{i}", r) for i, r in enumerate(v))
        return out or [("root", "", deposit)]
    return [("root", "", deposit)]


def _text(obj: Any) -> str:
    if isinstance(obj, dict):
        return " ".join(f"{k} {_text(v)}" for k, v in obj.items() if v != "[EXCLUIDO:pii]")
    if isinstance(obj, list):
        return " ".join(_text(v) for v in obj)
    return "" if obj is None else str(obj)


def import_deposit(conn: Conn, ctx: OpContext, *, deposit_bytes: bytes, schema_bytes: bytes, logical_path: str,
                   schema_path: str, source_system_code: str) -> dict[str, Any]:  # fmt: skip
    require(conn, ctx.principal, "source:write", Resource("source"))
    require(conn, ctx.principal, "import:write", Resource("import_batch"))
    dep_sha, sch_sha = sha256_hex(deposit_bytes), sha256_hex(schema_bytes)
    batch = legacy.create_batch(conn, ctx, source_system_code=source_system_code, batch_kind="knowledge_deposit",
                                parameters={"deposit": logical_path, "schema": schema_path,
                                            "deposit_sha256": dep_sha, "schema_sha256": sch_sha})  # fmt: skip
    batch_id = batch["batch_id"]
    legacy.transition(conn, ctx, batch_id, "staging")
    conn.execute("INSERT INTO legacy.raw_snapshots (snapshot_id, tenant_id, batch_id, object_name, sha256) "
                 "VALUES (%s,%s,%s,%s,%s)", (uuid7(), ctx.tenant_id, batch_id, logical_path, dep_sha))  # fmt: skip
    try:
        deposit = json.loads(deposit_bytes)
        schema = json.loads(schema_bytes)
    except json.JSONDecodeError as exc:
        legacy.quarantine(conn, ctx, batch_id, logical_path, None, "json_invalido", {"error": str(exc)[:200]})
        legacy.transition(conn, ctx, batch_id, "failed")
        return {"batch_id": batch_id, "status": "failed", "reason": "JSON inválido"}
    cls = validator_for(schema)
    cls.check_schema(schema)
    errors = list(cls(schema, format_checker=FormatChecker()).iter_errors(deposit))
    if errors:
        for err in errors[:50]:
            legacy.quarantine(conn, ctx, batch_id, logical_path, "/" + "/".join(map(str, err.path)),
                              "schema_violation", {"message": err.message[:300]})  # fmt: skip
        legacy.transition(conn, ctx, batch_id, "failed", {"read": 1, "rejected": 1})
        return {"batch_id": batch_id, "status": "failed", "schema_errors": len(errors)}

    existing = conn.execute("SELECT source_id FROM knowledge.sources WHERE sha256 = %s AND logical_path = %s",
                            (dep_sha, logical_path)).fetchone()  # fmt: skip
    if existing:
        legacy.transition(conn, ctx, batch_id, "failed")
        return {"batch_id": batch_id, "status": "duplicate", "source_id": existing["source_id"]}
    source_id = uuid7()
    conn.execute(
        """INSERT INTO knowledge.sources (source_id, tenant_id, name, kind, logical_path, sha256, size_bytes,
             classification, authority_rank, evidence_status, provenance, registered_by)
           VALUES (%s,%s,%s,'json_deposit',%s,%s,%s,'confidential',5,'INFERIDO_A_VALIDAR',%s,%s)""",
        (source_id, ctx.tenant_id, Path(logical_path).name, logical_path, dep_sha, len(deposit_bytes),
         Jsonb({"schema_path": schema_path, "schema_sha256": sch_sha, "batch_id": str(batch_id),
                "source_system_code": source_system_code}), ctx.principal.actor_id),
    )  # fmt: skip
    append(conn, ctx, EventDraft(event_type="knowledge.source_registered", aggregate_type="knowledge_source",
                                 aggregate_id=source_id, expected_version=0,
                                 payload={"kind": "json_deposit", "sha256": dep_sha, "authority_rank": 5,
                                          "evidence_status": "INFERIDO_A_VALIDAR"}))  # fmt: skip
    records = _records(deposit)
    created, excluded_total = 0, 0
    for idx, (collection, pointer, rec) in enumerate(records):
        excluded: list[str] = []
        body = sanitize(rec, pointer, excluded)
        excluded_total += len(excluded)
        key = f"{collection}:{rec.get('id', idx) if isinstance(rec, dict) else idx}"
        title = (
            str(rec.get("name") or rec.get("nome") or rec.get("table") or key)
            if isinstance(rec, dict)
            else key
        )
        node_id = uuid7()
        conn.execute(
            """INSERT INTO knowledge.nodes (node_id, tenant_id, source_id, node_type, node_key, title, body,
                 provenance) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (node_id, ctx.tenant_id, source_id, f"deposit.{collection}", key, title[:300],
             Jsonb(body if isinstance(body, dict) else {"value": body}),
             Jsonb({"file": logical_path, "json_pointer": pointer, "file_sha256": dep_sha,
                    "record_sha256": sha256_hex(canonical_json(rec))})),
        )  # fmt: skip
        text = _text(body)[:8000]
        if text.strip():
            conn.execute(
                "INSERT INTO knowledge.chunks (chunk_id, tenant_id, node_id, ordinal, text_content, embedding, "
                "embedding_model, excluded_fields) VALUES (%s,%s,%s,0,%s,%s::vector,%s,%s)",
                (uuid7(), ctx.tenant_id, node_id, text, str(embed(text)), EMBEDDING_MODEL, excluded),
            )
        created += 1
    legacy.transition(conn, ctx, batch_id, "validated",
                      {"read": len(records), "accepted": created, "transformed": created,
                       "rejected": len(records) - created, "orphans": 0})  # fmt: skip
    r1 = legacy.reconcile(conn, ctx, batch_id, "count", "registos lidos vs nós criados", str(len(records)),
                          str(created))  # fmt: skip
    stored = conn.execute(
        "SELECT sha256 FROM knowledge.sources WHERE source_id = %s", (source_id,)
    ).fetchone()
    r2 = legacy.reconcile(
        conn, ctx, batch_id, "hash", "sha256 depósito", dep_sha, stored["sha256"] if stored else None
    )
    final = "reconciled" if r1 == r2 == "pass" else "failed"
    legacy.transition(conn, ctx, batch_id, final)
    append(conn, ctx, EventDraft(event_type="knowledge.deposit_imported", aggregate_type="knowledge_source",
                                 aggregate_id=source_id,
                                 payload={"source_id": source_id, "schema_sha256": sch_sha, "nodes_created": created,
                                          "fields_excluded": excluded_total}))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="knowledge.import",
        resource_type="knowledge_source",
        resource_id=source_id,
        outcome="succeeded" if final == "reconciled" else "failed",
        details={"batch_id": str(batch_id), "nodes": created, "excluded": excluded_total},
    )
    return {"batch_id": batch_id, "source_id": source_id, "status": final, "nodes_created": created,
            "fields_excluded": excluded_total, "deposit_sha256": dep_sha}  # fmt: skip


def search(conn: Conn, ctx: OpContext, query: str, limit: int = 5) -> list[dict[str, Any]]:
    require(conn, ctx.principal, "knowledge:read", Resource("knowledge"))
    from we_core.identity.authz import scope_sql

    where, params = scope_sql(ctx.principal, org_col=None, classification=True)
    vec = str(embed(query))
    sql = (
        "SELECT n.node_id, n.title, n.provenance, c.embedding <=> %s::vector AS distance FROM knowledge.chunks c "
        "JOIN knowledge.nodes n ON n.tenant_id = c.tenant_id AND n.node_id = c.node_id "
        f"WHERE {where.replace('classification', 'n.classification')} "
        "ORDER BY c.embedding <=> %s::vector LIMIT %s"
    )
    return [dict(r) for r in conn.execute(sql.encode(), (vec, *params, vec, limit)).fetchall()]


def import_deposit_cli(settings: Settings, tenant_id: UUID, actor_subject: str, deposit: Path,
                       schema: Path, source_system_code: str) -> dict[str, Any]:  # fmt: skip
    from we_core.identity.principal import resolve_principal

    if not deposit.is_file() or not schema.is_file():
        raise ValidationFailed("Depósito ou schema inexistente.")
    db = Database(settings.dsn("app"), 1, 2)
    db.open()
    try:
        principal = resolve_principal(
            db, settings, {"sub": actor_subject, settings.oidc_tenant_claim: str(tenant_id)}
        )
        ctx = OpContext(principal=principal)
        with db.tenant_tx(tenant_id) as conn:
            return import_deposit(conn, ctx, deposit_bytes=deposit.read_bytes(), schema_bytes=schema.read_bytes(),
                                  logical_path=deposit.as_posix(), schema_path=schema.as_posix(),
                                  source_system_code=source_system_code)  # fmt: skip
    finally:
        db.close()
