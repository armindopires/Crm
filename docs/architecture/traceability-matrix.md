# Matriz de rastreabilidade (requisito → fonte → decisão → implementação → teste)

Fonte "P§n" = prompt mestre, secção n (autoridade 1). As fontes do pacote estão ausentes (ADR-0014).

| # | Requisito | Fonte | Decisão | Implementação | Teste / evidência |
|---|---|---|---|---|---|
| R01 | PostgreSQL fonte de verdade; restantes sistemas reconstruíveis | P§5, P§12 | ADR-0002 | `db/migrations/0002`, `events/store.py` | demo passo 11; `test_consumer_is_idempotent_and_replay_is_deterministic` |
| R02 | Modular monolith event-driven | P§6 | ADR-0001 | `src/we_core/*` | revisão de arquitetura |
| R03 | tenant_id + RLS deny-by-default + FKs delimitadas | P§11 | ADR-0003 | `0001` (`enable_tenant_rls`), FKs compostas | `test_rls_denies_everything_without_tenant_context`, `test_tenant_cannot_write_into_another` |
| R04 | Tenant de claims assinadas, não de header | P§11 | ADR-0003/0006 | `identity/oidc.py`, `identity/principal.py` | demo passo 13 (claim forjada 403, assinatura falsa 401); `test_identity.py` |
| R05 | Contexto sem fuga em pools | P§11 | ADR-0003 | `db.tenant_tx` (`set_config` local) | `test_tenant_context_does_not_leak_through_pool` |
| R06 | RBAC + ABAC | P§11 | ADR-0003 | `identity/authz.py`, `iam.policies` | `test_authz.py`, `test_restricted_evidence_policy_requires_audit_purpose` |
| R07 | Envelope versionado e completo | P§12 | ADR-0013 | `event-envelope.v1.schema.json`, `events/store.py` | `test_contracts.py` |
| R08 | Append-only por privilégio | P§12, P§13 | ADR-0002 | GRANTs + `platform.make_append_only` | `test_app_role_cannot_update_delete_or_truncate_history` |
| R09 | Concorrência otimista + idempotência | P§12, P§20 | ADR-0002 | `aggregate_version`, `idempotency_key`, `api.idempotency_keys`, If-Match | demo passos 3 e 4; `test_event_idempotency_and_optimistic_concurrency` |
| R10 | Outbox, retry, backoff, DLQ, consumidores idempotentes | P§12 | ADR-0009 | `events/outbox.py`, `worker/main.py` | `test_outbox_retries_then_dead_letters_then_requeue`; demo passo 5 |
| R11 | AsyncAPI + evolução compatível | P§12, P§16 | ADR-0013 | `contracts/asyncapi`, `scripts/export_openapi.py` | `validate-asyncapi.mjs`; `test_schema_evolution_is_backward_compatible` |
| R12 | Evidência imutável, SHA-256 no servidor, custódia | P§13 | ADR-0004 | `evidence/*` | demo passo 6; `test_evidence_tampering_is_detected` |
| R13 | Auditoria append-only, cadeia de hash, sem PII | P§13 | ADR-0007/0013 | `audit/log.py`, `integrity.py` | `test_tampering_is_detected_in_event_and_audit_chains`; demo passo 12 |
| R14 | Estados de decisão + HITL + IA não executa | P§13 | ADR-0010 | `governance/service.py` + trigger 0004 | demo passos 7–9; `test_decision_guard_in_database_enforces_hitl_and_sod` |
| R15 | AI_TRACE e gateway com allowlist | P§13 | ADR-0010 | `ai/gateway.py`, `ai.ai_traces` | demo passo 7 |
| R16 | Context frames como snapshots versionados | P§10 | ADR-0002 | `kernel.context_frames` (append-only) | `test_context_frames_are_versioned_not_mutated` |
| R17 | Dinheiro exato + ISO 4217; identificadores como texto | P§10 | ADR-0008 | `numeric(18,2)`, `char(3)`, `entity_identifiers.value_text` | demo passo 10 |
| R18 | Regras normativas versionadas com validação externa | P§4, P§10 | ADR-0012 | `obligation.rule_catalog` (CHECK `production_enabled`) | revisão de schema (sem regras reais) |
| R19 | Knowledge com hash, proveniência e schema antes de importar | P§14 | ADR-0011 | `knowledge/importer.py`, `manifest.py` | `test_knowledge_import_validates_schema_and_excludes_secrets`; `test_manifest_flags_missing_sources_and_blocks_zip_slip` |
| R20 | Segredos e PII fora de embeddings e índices | P§14, P§17 | ADR-0011 | `importer.sanitize` | idem R19 |
| R21 | Staging legado, quarentena, reconciliação, sem segredos | P§15 | ADR-0012 | `legacy/service.py`, `legacy.*` | idem R19 (quarentena e reconciliação) |
| R22 | OpenAPI + problem+json + SDK gerado | P§16 | — | `api/app.py`, `packages/sdk-typescript` | `test_contracts.py`; `tsc` |
| R23 | UI mínima PT-PT, responsiva e acessível | P§16 | — | `apps/web` | captura 390 px sem scroll horizontal; `lang="pt-PT"`, skip link, labels |
| R24 | Containers não-root, read-only | P§17 | — | Dockerfiles + compose | `docker exec … id` → uid 10001 / node |
| R25 | Logs, métricas e traces; health/ready | P§18 | — | `observability.py`, `/metrics`, `/health/*` | `/health/ready` na demo; métricas de outbox, DLQ, decisões e integridade |
| R26 | CI completo | P§19 | — | `.github/workflows/ci.yml` | não executado neste ambiente (ver STATUS) |
| R27 | Demonstração vertical | P§20 | — | `scripts/demo_vertical.py` | 14/14 OK (local e em contentores) |
| R28 | Seeds apenas sintéticos | P§5 | — | `db/seeds`, domínios `.invalid` | revisão + gitleaks |
