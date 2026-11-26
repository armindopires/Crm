# Threat model inicial (STRIDE)

Âmbito: API, worker, PostgreSQL, NATS, armazenamento S3, Redis e consola web (perfil core + ui).
Ativos: dados de clientes (confidential/restricted), evidências, cadeias de integridade, decisões, credenciais.

| STRIDE | Ameaça | Controlo implementado | Evidência | Residual |
|---|---|---|---|---|
| **S**poofing | Token forjado ou de outro IdP | JWKS, `iss`/`aud`/`exp`, algoritmos restritos, `kid` obrigatório | `test_identity.py`; demo passo 13 (401) | IdP produtivo por decidir |
| S | Claim de tenant manipulada | Tenant só da claim assinada + ator e membership existentes nesse tenant | demo passo 13 (403) | — |
| S | IA a fazer-se passar por humano | `actor_type` vem da BD, não do token; `HUMAN_ONLY`; trigger HITL | `test_authz.py`; trigger 0004 | — |
| **T**ampering | Alteração de eventos ou auditoria | Append-only (GRANT + trigger) + cadeias de hash | `test_tampering_is_detected…` | DBA pode reescrever a cadeia → ancoragem externa (G04) |
| T | Alteração de evidência no armazenamento | SHA-256 no servidor + verificação + custódia | `test_evidence_tampering_is_detected` | Sem WORM em dev (G03) |
| T | Transições ilegais de decisão por SQL | Trigger `guard_decision_transition` | `test_decision_guard…` | — |
| **R**epudiation | Negar autoria de uma aprovação | `governance.approvals` append-only + auditoria com pseudónimo HMAC + correlação | demo passo 9 | Chave HMAC requer rotação (runbook) |
| **I**nformation disclosure | Fuga entre tenants | RLS FORCE, FKs compostas, 404 sem enumeração, contexto local à transação | testes de isolamento; demo passo 13 | Superuser contorna (acesso de DBA auditado: pendente) |
| I | PII ou segredos em eventos, logs e embeddings | Schemas fechados; redação de logs; `sanitize` do importador; atributos de segredo recusados | `test_security_helpers.py`; `test_secrets_are_refused…` | Redação heurística |
| I | Credenciais legadas (Firebird/DBISAM) | Nunca migradas (`CHECK` em `mapping_rules`); parâmetros de lote sem credenciais; utilitários não executados | `legacy/service.py`; manifest | — |
| I | Path traversal / zip-slip | `safe_filename`; extração com verificação de `..`/absolutos | `test_safe_filename…`, `test_manifest…zip_slip` | — |
| **D**oS | Abuso de API | Rate limit por tenant (Redis); limite de upload; paginação limitada | `deps._rate_limit` | Fail-open sem Redis (G10) |
| D | Broker indisponível | Outbox persiste; retry/backoff; DLQ | `test_outbox_retries…` | — |
| **E**levation of privilege | SQL injection | Sempre parametrizado; nomes dinâmicos só de listas fixas | revisão de código; ruff `S` | — |
| E | Command injection / shell arbitrário | Não há execução de comandos em endpoints, agentes ou workflows; IA sem efeitos laterais | AI gateway allowlist | — |
| E | SSRF | A API não faz pedidos a URLs fornecidos pelo utilizador; endpoint S3 fixo por configuração | revisão | — |
| E | XSS/CSRF na web | React escapa output; CSP restritiva; server actions com validação de UUID; token nunca no browser | `next.config.mjs` | Sessão OIDC pendente (G08) |
| E | Contentor comprometido | Não-root, `read_only`, `cap_drop: ALL`, `no-new-privileges`, sem pip em runtime | compose, Dockerfiles | — |

Revisão: a cada novo conector, capacidade com efeitos externos ou fornecedor de IA.
