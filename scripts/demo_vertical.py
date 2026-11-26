#!/usr/bin/env python3
"""Demonstração vertical E2E da WE (repetível; apenas dados sintéticos).

Pré-requisitos: perfil core a correr (API + worker) e `.local/` gerado pelo bootstrap.
Uso: uv run python scripts/demo_vertical.py [--api http://localhost:8000] [--report reports/demo.json]
Sai com código ≠ 0 se qualquer verificação falhar.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from we_core.config import get_settings
from we_core.identity.devissuer import mint_token

RESULTS: list[dict[str, Any]] = []


def step(n: int, title: str, ok: bool, evidence: Any = None) -> None:
    RESULTS.append({"step": n, "title": title, "ok": ok, "evidence": evidence})
    mark = "OK " if ok else "FALHA"
    print(f"[{mark}] {n:>2}. {title}" + (f" — {evidence}" if evidence is not None else ""), flush=True)
    if not ok:
        raise SystemExit(f"Falhou o passo {n}: {title}")


class Client:
    def __init__(self, base: str, token: str) -> None:
        self.c = httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}, timeout=20)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.c, name)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=os.environ.get("WE_API_URL", "http://localhost:8000"))
    ap.add_argument("--report", default="reports/demo-vertical.json")
    ap.add_argument("--web-token-out", default=".local/web-token")
    args = ap.parse_args()
    s = get_settings()
    run = secrets.token_hex(3)
    api = args.api.rstrip("/")

    ready = httpx.get(f"{api}/health/ready", timeout=10).json()
    step(0, "API pronta (health/ready)", ready["status"] in ("ok", "degraded"), ready["checks"])

    # 1. Tenant + organização sintéticos
    platform = Client(api, mint_token(s, "platform-admin@dev.we.invalid", platform_roles=["platform_admin"]))
    admin_sub = f"admin-{run}@alfa.example.invalid"
    r = platform.post(
        "/v1/tenants",
        json={
            "slug": f"demo-alfa-{run}",
            "display_name": f"Gabinete Fictício Alfa {run}",
            "organization_name": "Alfa Contabilidade Fictícia, Lda.",
            "admin_subject": admin_sub,
            "admin_display_name": "Administradora Fictícia",
            "is_synthetic": True,
        },
    )
    step(1, "Criar tenant e organização sintéticos", r.status_code == 201, r.json().get("tenant_id"))
    tenant = r.json()
    tid, org_id = tenant["tenant_id"], tenant["organization_id"]
    admin = Client(api, mint_token(s, admin_sub, tenant_id=tid))

    # 2. Ator, papel e política
    actors = {}
    for key, atype, roles, clr in (
        ("operator", "human", ["operator"], "confidential"),
        ("approver", "human", ["approver"], "confidential"),
        ("agent", "ai_agent", ["ai_agent"], "confidential"),
    ):
        sub = f"{key}-{run}@alfa.example.invalid"
        r = admin.post(
            "/v1/actors",
            json={
                "idp_subject": sub,
                "actor_type": atype,
                "roles": roles,
                "display_name": f"{key.title()} Fictício",
                "clearance": clr,
            },
        )
        assert r.status_code == 201, r.text
        actors[key] = Client(api, mint_token(s, sub, tenant_id=tid))
    r = admin.post(
        "/v1/policies",
        json={
            "name": "evidence.restricted.audit-only",
            "effect": "deny",
            "actions": ["evidence:read"],
            "conditions": {"classification_in": ["restricted"], "purpose_not_in": ["audit"]},
            "description": "Evidência restrita só pode ser lida com finalidade de auditoria.",
        },
    )
    step(
        2,
        "Criar atores (operador, aprovador, agente IA), papéis RBAC e política ABAC",
        r.status_code == 201,
        f"policy v{r.json().get('version')}",
    )
    op, approver, agent = actors["operator"], actors["approver"], actors["agent"]

    # 3. Entity + Context frame
    r = op.post(
        "/v1/context-frames",
        json={
            "frame_key": f"cliente-ficticio-{run}:onboarding",
            "purpose": "Onboarding de cliente fictício",
            "organization_id": org_id,
            "snapshot": {"fase": "onboarding", "periodo": "2026-Q4", "sintetico": True},
        },
    )
    frame = r.json()
    idem = f"demo-{run}-entity-create"
    body = {
        "entity_type": "client_company",
        "display_name": "Cliente Fictício Beta, S.A.",
        "classification": "confidential",
        "organization_id": org_id,
        "context_frame_id": frame["context_frame_id"],
        "attributes": {"setor": "servicos", "regime_iva": "NAO_INDICADO", "sintetico": True},
    }
    r1 = op.post("/v1/entities", json=body, headers={"Idempotency-Key": idem})
    step(
        3,
        "Criar CONTEXT_FRAME e ENTITY",
        r1.status_code == 201 and r.status_code == 201,
        {"entity_id": r1.json()["entity_id"], "frame_version": frame["version"]},
    )
    entity = r1.json()
    eid = entity["entity_id"]

    r2 = op.post("/v1/entities", json=body, headers={"Idempotency-Key": idem})
    evs = op.get("/v1/events", params={"aggregate_id": eid}).json()["items"]
    step(
        3,
        "Repetir Idempotency-Key não cria segundo efeito",
        r2.json()["entity_id"] == eid and r2.headers.get("Idempotent-Replayed") == "true" and len(evs) == 1,
        {"eventos_da_entidade": len(evs)},
    )

    # 4. Alteração material + EVENT (concorrência otimista)
    r = op.patch(
        f"/v1/entities/{eid}",
        json={
            "attributes": {**body["attributes"], "regime_iva": "normal_mensal"},
            "context_frame_id": frame["context_frame_id"],
        },
        headers={"If-Match": '"1"'},
    )
    stale = op.patch(f"/v1/entities/{eid}", json={"status": "archived"}, headers={"If-Match": '"1"'})
    evs = op.get("/v1/events", params={"aggregate_id": eid}).json()["items"]
    step(
        4,
        "Alteração material gera EVENT; If-Match desatualizado → 412",
        r.status_code == 200 and r.json()["version"] == 2 and stale.status_code == 412 and len(evs) == 2,
        {"event_types": [e["event_type"] for e in evs], "changed": evs[-1]["payload"]["changed_fields"]},
    )

    # 5. Outbox → EventBus sem duplicação (requer worker)
    deadline, ob = time.time() + 30, {}
    while time.time() < deadline:
        ob = admin.get("/v1/admin/outbox").json()
        proj = op.get(f"/v1/projections/entity-summary/{eid}")
        if ob["pending"] == 0 and proj.status_code == 200 and proj.json()["event_count"] == 2:
            break
        time.sleep(0.5)
    proj_json = proj.json() if proj.status_code == 200 else {}
    step(
        5,
        "Outbox publicada no NATS e projeção aplicada sem duplicação",
        ob.get("pending") == 0 and ob.get("dead") == 0 and proj_json.get("event_count") == 2,
        {"outbox": ob, "entity_summary.event_count": proj_json.get("event_count")},
    )

    # 6. Evidence com SHA-256
    content = f"Declaração sintética de teste {run}\nDocumento fictício — sem valor legal.\n".encode()
    local_sha = hashlib.sha256(content).hexdigest()
    r = op.post(
        "/v1/evidence",
        files={"file": ("declaracao-ficticia.txt", content, "text/plain")},
        data={"classification": "confidential", "source": "demo", "organization_id": org_id},
    )
    ev = r.json()
    ver = op.post(f"/v1/evidence/{ev['evidence_id']}/verify").json()
    step(
        6,
        "Anexar EVIDENCE e confirmar SHA-256 no servidor",
        r.status_code == 201 and ev["sha256"] == local_sha and ver["valid"],
        {"sha256": local_sha[:16] + "…"},
    )

    # 7. DECISION proposta pela IA (com AI_TRACE) ligada a contexto e evidência
    ai = agent.post(
        "/v1/ai/invoke",
        json={
            "capability": "propose_decision",
            "text": "Cliente fictício mudou para regime mensal de IVA.",
            "params": {
                "title": "Ajustar calendário de obrigações do cliente fictício",
                "impact_category": "fiscal",
            },
        },
    )
    trace = ai.json()
    r = agent.post(
        "/v1/decisions",
        json={
            "title": trace["output"]["title"],
            "description": trace["output"]["rationale"],
            "decision_type": "obligation_calendar_change",
            "impact_category": "fiscal",
            "context_frame_id": frame["context_frame_id"],
            "evidence_ids": [ev["evidence_id"]],
            "ai_trace_id": trace["ai_trace_id"],
        },
    )
    dec = r.json()
    step(
        7,
        "IA propõe DECISION ligada a CONTEXT_FRAME, EVIDENCE e AI_TRACE",
        r.status_code == 201 and dec["status"] == "proposed",
        {"decision_id": dec["decision_id"]},
    )
    did = dec["decision_id"]

    # 8. Execução bloqueada antes da aprovação humana
    ex = op.post(f"/v1/decisions/{did}/execute")
    ai_review = agent.post(f"/v1/decisions/{did}/review", json={"verdict": "approved", "rationale": "auto"})
    step(
        8,
        "Execução bloqueada sem aprovação humana; IA não pode aprovar",
        ex.status_code == 409 and ex.json()["code"] == "WE-GOV-HITL" and ai_review.status_code == 403,
        {"execute": ex.json()["code"], "ai_review": ai_review.json()["code"]},
    )

    # 9. Aprovação humana + AUDIT_LOG append-only
    ap_r = approver.post(
        f"/v1/decisions/{did}/review",
        json={"verdict": "approved", "rationale": "Validado com base na evidência anexa."},
    )
    ex2 = op.post(f"/v1/decisions/{did}/execute")
    audit = admin.get("/v1/audit", params={"limit": 500}).json()["items"]
    actions = {(a["action"], a["outcome"]) for a in audit}
    step(
        9,
        "Aprovação humana explícita, execução registada e AUDIT_LOG",
        ap_r.status_code == 200
        and ex2.status_code == 200
        and ex2.json()["status"] == "executed"
        and ("decision.approve", "succeeded") in actions
        and ("http.post", "denied") in actions,
        {"audit_records": len(audit)},
    )

    # 10. SIGNAL → OPPORTUNITY
    sg = op.post(
        "/v1/signals",
        json={
            "signal_type": "regime_change",
            "source": "demo",
            "strength": "0.8",
            "description": "Alteração de regime sugere revisão de serviços.",
            "entity_id": eid,
            "context_frame_id": frame["context_frame_id"],
        },
    ).json()
    opp = op.post(
        f"/v1/signals/{sg['signal_id']}/promote",
        json={
            "title": "Serviço de apoio ao regime mensal (fictício)",
            "value_estimate": "1200.00",
            "currency": "EUR",
        },
    )
    step(
        10,
        "Criar SIGNAL e promover a OPPORTUNITY",
        opp.status_code == 201,
        {"value": f"{opp.json()['value_estimate']} {opp.json()['currency']}"},
    )

    # 11. Replay
    rp = admin.post("/v1/admin/projections/entity_summary/replay").json()
    step(
        11,
        "Reconstruir projeção por replay (determinístico e igual à projeção viva)",
        rp["deterministic"] and rp["matches_live"],
        {"events": rp["events_replayed"], "digest": rp["after"]["sha256"][:16]},
    )

    # 12. Integridade
    ve = admin.get("/v1/events/verify").json()
    va = admin.get("/v1/audit/verify").json()
    step(
        12,
        "Verificar cadeias de integridade (eventos e auditoria)",
        ve["valid"] and va["valid"],
        {"events": ve["records"], "audit": va["records"]},
    )

    # 13. Isolamento entre tenants
    sub_b = f"admin-{run}@beta.example.invalid"
    tb = platform.post(
        "/v1/tenants",
        json={
            "slug": f"demo-beta-{run}",
            "display_name": f"Gabinete Fictício Beta {run}",
            "organization_name": "Beta Fictícia, Lda.",
            "admin_subject": sub_b,
            "admin_display_name": "Admin Beta Fictício",
        },
    ).json()
    b = Client(api, mint_token(s, sub_b, tenant_id=tb["tenant_id"]))
    cross_entity = b.get(f"/v1/entities/{eid}").status_code
    cross_evidence = b.get(f"/v1/evidence/{ev['evidence_id']}").status_code
    cross_decision = b.get(f"/v1/decisions/{did}").status_code
    cross_list = [x["entity_id"] for x in b.get("/v1/entities").json()["items"]]
    cross_events = list(b.get("/v1/events", params={"aggregate_id": eid}).json()["items"])
    spoof = Client(api, mint_token(s, sub_b, tenant_id=tid)).get("/v1/entities").status_code
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged_tok = jwt.encode({"iss": s.oidc_issuer, "aud": s.oidc_audience, "sub": admin_sub, "we_tenant_id": tid,
                             "iat": int(time.time()), "exp": int(time.time()) + 60}, other_key, algorithm="RS256",
                            headers={"kid": "we-dev-key-1"})  # fmt: skip
    forged = Client(api, forged_tok).get("/v1/entities").status_code
    step(
        13,
        "Segundo tenant: acesso cruzado negado (sem enumeração), claim forjada e assinatura falsa rejeitadas",
        cross_entity == 404
        and cross_evidence == 404
        and cross_decision == 404
        and eid not in cross_list
        and not cross_events
        and spoof == 403
        and forged == 401,
        {
            "entity": cross_entity,
            "evidence": cross_evidence,
            "decision": cross_decision,
            "tenant_spoof": spoof,
            "forged_signature": forged,
        },
    )

    # 14. Resultado na API e interface mínima
    st = admin.get("/v1/system/status").json()
    Path(args.web_token_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.web_token_out).write_text(mint_token(s, admin_sub, tenant_id=tid, ttl_seconds=8 * 3600))
    # 0644: o contentor web corre como utilizador não-root distinto. Token só de dev, local, TTL 8h (risco aceite).
    with contextlib.suppress(OSError):
        os.chmod(args.web_token_out, 0o644)
    step(
        14,
        "Estado agregado disponível na API (e token local para a interface)",
        st["chains"]["events"] and st["chains"]["audit"],
        st["counts"],
    )

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps({"run": run, "tenant_id": tid, "results": RESULTS}, indent=2,
                                            default=str, ensure_ascii=False))  # fmt: skip
    print(f"\nDemonstração concluída: {len(RESULTS)} verificações OK. Relatório: {args.report}")
    print("Interface: http://localhost:3000 (perfil ui)")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as exc:
        print(f"BLOCKED: API inacessível ({exc}). Arranque o perfil core: python scripts/dev.py start")
        sys.exit(2)
