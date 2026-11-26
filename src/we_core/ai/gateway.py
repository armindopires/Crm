"""Gateway de IA: allowlist de capacidades, efeitos laterais bloqueados por defeito, AI_TRACE obrigatório.

O domínio não depende de um fornecedor: `AIProvider` é uma porta. Nesta fase só existe o
`LocalHeuristicProvider` (determinístico, sem chamadas externas). Integrar um LLM real exige ADR e DPIA.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from psycopg.types.json import Jsonb

from we_core.audit import log as audit
from we_core.common import canonical_json, sha256_hex, uuid7
from we_core.config import get_settings
from we_core.context import OpContext
from we_core.db import Conn
from we_core.errors import Forbidden, ValidationFailed
from we_core.events.store import EventDraft, append
from we_core.identity.authz import Resource, require

CAPABILITIES = {"summarize", "classify", "propose_decision"}  # allowlist; nada com efeitos externos
PROMPT_TEMPLATES = {
    "summarize": ("tpl.summarize", "1.0.0"),
    "classify": ("tpl.classify", "1.0.0"),
    "propose_decision": ("tpl.propose_decision", "1.0.0"),
}
_REDACT = [
    (re.compile(r"\b\d{9}\b"), "[NUM9]"),  # possíveis NIF/NISS-like
    (re.compile(r"\bPT50\d{21}\b"), "[IBAN]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[EMAIL]"),
]


def redact(text: str) -> str:
    for rx, rep in _REDACT:
        text = rx.sub(rep, text)
    return text


@dataclass
class AIResult:
    output: dict[str, Any]
    tokens_in: int | None = None
    tokens_out: int | None = None
    tools_called: list[str] = field(default_factory=list)


class AIProvider(Protocol):
    name: str
    model: str

    def run(self, capability: str, text: str, params: dict[str, Any]) -> AIResult: ...


class LocalHeuristicProvider:
    name = "local"
    model = "we-heuristic-0"

    def run(self, capability: str, text: str, params: dict[str, Any]) -> AIResult:
        words = text.split()
        if capability == "summarize":
            out: dict[str, Any] = {"summary": " ".join(words[:40])}
        elif capability == "classify":
            label = "fiscal" if re.search(r"\b(iva|irc|irs|imposto|fiscal)\b", text, re.I) else "interno"
            out = {"label": label}
        else:
            out = {
                "title": params.get("title") or "Proposta gerada para validação humana",
                "rationale": "Proposta automática baseada no contexto fornecido. Requer validação humana.",
                "impact_category": params.get("impact_category", "interno"),
            }
        return AIResult(out, tokens_in=len(words), tokens_out=len(canonical_json(out).split()))


def invoke(conn: Conn, ctx: OpContext, provider: AIProvider, *, capability: str, text: str,
           params: dict[str, Any] | None = None, side_effects: str = "blocked") -> dict[str, Any]:  # fmt: skip
    require(conn, ctx.principal, "ai:invoke", Resource("ai", attributes={"capability": capability}))
    if capability not in CAPABILITIES:
        raise Forbidden(f"Capacidade de IA não autorizada: {capability}", code="WE-AI-CAP")
    if side_effects != "blocked":
        raise ValidationFailed("Efeitos laterais de IA estão bloqueados nesta fase.", code="WE-AI-SIDEFX")
    params = params or {}
    safe_text = redact(text)
    result = provider.run(capability, safe_text, params)
    tpl_id, tpl_ver = PROMPT_TEMPLATES[capability]
    trace_id = uuid7()
    # HMAC com chave secreta: impede força bruta de inputs curtos (ex.: NIF) a partir do hash publicado
    key = (get_settings().audit_pseudonym_key.get_secret_value() or "dev-only-pseudonym-key").encode()
    in_hash = hmac.new(key, text.encode(), hashlib.sha256).hexdigest()
    out_hash = sha256_hex(canonical_json(result.output))
    conn.execute(
        """INSERT INTO ai.ai_traces (ai_trace_id, tenant_id, provider, model, capability, prompt_template_id,
             prompt_version, input_hash, output_hash, input_ref, output_summary, tools_called, parameters,
             tokens_in, tokens_out, policy_refs, side_effects, requested_by, correlation_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'blocked',%s,%s)""",
        (trace_id, ctx.tenant_id, provider.name, provider.model, capability, tpl_id, tpl_ver, in_hash, out_hash,
         f"redacted:{sha256_hex(safe_text)[:16]}", canonical_json(result.output)[:500],
         Jsonb(result.tools_called), Jsonb({k: v for k, v in params.items() if k in ("impact_category",)}),
         result.tokens_in, result.tokens_out, Jsonb(["ai:allowlist", "ai:side_effects_blocked"]),
         ctx.principal.actor_id, ctx.correlation_id),
    )  # fmt: skip
    append(conn, ctx, EventDraft(
        event_type="ai.inference_traced", aggregate_type="ai_trace", aggregate_id=trace_id, expected_version=0,
        payload={"provider": provider.name, "model": provider.model, "capability": capability,
                 "input_hash": in_hash, "output_hash": out_hash, "side_effects": "blocked"},
    ))  # fmt: skip
    audit.record(
        conn,
        ctx,
        action="ai.invoke",
        resource_type="ai_trace",
        resource_id=trace_id,
        outcome="succeeded",
        policy_refs=["ai:allowlist", "ai:side_effects_blocked"],
        details={"capability": capability},
    )
    return {"ai_trace_id": trace_id, "capability": capability, "output": result.output,
            "provider": provider.name, "model": provider.model}  # fmt: skip


def get_trace(conn: Conn, ctx: OpContext, trace_id: UUID) -> dict[str, Any] | None:
    require(conn, ctx.principal, "decision:read", Resource("ai_trace", trace_id))
    row = conn.execute("SELECT * FROM ai.ai_traces WHERE ai_trace_id = %s", (trace_id,)).fetchone()
    return dict(row) if row else None
