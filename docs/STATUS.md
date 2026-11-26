# STATUS — Wolf Enterprise (fundação)

Data: 2026-11-26 · Branch: `claude/wolf-enterprise-foundation-v2esle`

> Não é *production-ready*. Não tem certificação AT nem conformidade normativa completa. Ambiente de
> desenvolvimento com dados exclusivamente sintéticos.

## Concluído e validado (com evidência)

| Área | Evidência |
|---|---|
| Migrações | 10 migrações aplicadas numa base vazia; re-execução idempotente; checksums verificados |
| Multi-tenancy / RLS | Todas as tabelas de domínio com RLS FORCE (verificado por consulta ao catálogo); testes de leitura, escrita, enumeração, FK cruzada e fuga em pool |
| Event Store | Append-only (UPDATE/DELETE/TRUNCATE recusados ao `we_app`); concorrência otimista; idempotência; cadeia de hash por tenant |
| Outbox / NATS | Publicação at-least-once com deduplicação; retry, backoff e DLQ testados; lease de publicador único; ordem por tenant preservada após retry |
| Projeções | Consumidor idempotente; replay determinístico (rebuild duplo + digest) |
| Evidência | SHA-256 no servidor; adulteração do objeto detetada; cadeia de custódia |
| Auditoria | Cadeia de hash; adulteração por DBA detetada (teste); pseudonimização HMAC |
| Governação | HITL + segregação de funções na API **e** na BD; colunas imutáveis; aprovação exige registo em `approvals` |
| IA | Allowlist; efeitos laterais bloqueados; AI_TRACE com hash de input por HMAC |
| Knowledge | Manifesto de fontes; importador validado por schema; quarentena; segredos descartados; PII fora de embeddings |
| API / contratos | OpenAPI exportado e testado; AsyncAPI válido (28 canais, 29 mensagens); problem+json PT-PT; SDK TS gerado |
| UI | Consola Next.js PT-PT, 6 vistas; sem scroll horizontal a 390 px; contentor não-root |
| Demo vertical | **14/14 passos OK** em processos locais e em contentores (`scripts/demo_vertical.py`) |
| Testes | **56 testes**: 28 unitários, 4 de contrato, 24 de integração adversarial |
| Qualidade | ruff (lint + format) e mypy `--strict` sem erros; `tsc` sem erros; build web sem avisos |
| Segurança | gitleaks: 0 fugas · pip-audit: 0 · pnpm audit: 0 · trivy: 0 CRITICAL (1 HIGH Debian sem correção publicada no repositório) · SBOM CycloneDX das 2 imagens |
| Backup / restore | `pg_dump` → restore numa base nova: contagens idênticas; cadeias válidas em todos os tenants legítimos. As 11 inválidas são os tenants `tamper-*` adulterados de propósito pelos testes |

## Revisão independente (Fase 5)

13 achados de um revisor independente, todos confirmados no código. **12 corrigidos integralmente** e **1
parcialmente** (#9: a idempotência fica ligada ao ator; a revalidação de permissões no replay fica PENDENTE).

| # | Achado | Estado |
|---|---|---|
| 1 | Bloqueio do event loop (upload async + auditoria de negação) e sem `lock_timeout` | Corrigido (upload em threadpool; `run_in_threadpool`; timeouts por role, migração 0010) |
| 2 | Trigger HITL contornável por alteração de `requires_human_approval` | Corrigido (GRANT por coluna; imutabilidade; registo de aprovação obrigatório) + teste |
| 3 | `/system/status` sem autorização e com leitura ilimitada | Corrigido (`event:verify` + `audit:verify`; cursores de servidor) |
| 4 | Âmbito organizacional ignorado em listagens e gets | Corrigido (`scope_sql`) + teste |
| 5 | Hash do input de IA sujeito a força bruta | Corrigido (HMAC) + teste |
| 6 | Eventos com classificação mais baixa que o recurso | Corrigido (evidência herda; decisões `confidential`) |
| 7 | Falsa "truncagem" na verificação concorrente | Corrigido (cabeça lida primeiro) + teste |
| 8 | Ordem por tenant perdida após retry | Corrigido (bloqueio de eventos posteriores a um pendente em espera) |
| 9 | Replay idempotente não ligado ao ator | Corrigido parcialmente (ator no hash e na verificação) |
| 10 | Admin atribui habilitação acima da sua | Corrigido + teste |
| 11 | Condições de política não validadas (DoS do tenant) | Corrigido + teste |
| 12 | Fontes e pesquisa sem filtro de habilitação | Corrigido |
| 13 | UPDATE amplo em `iam.actors` (permite mudar `actor_type`) | Corrigido (GRANT por coluna) + teste |
| — | Floats em payloads quebrariam o hash após JSONB | Prevenido (rejeição explícita) + teste |

## Bloqueado (BLOCKED) neste ambiente

| Item | Motivo | Comando para executar |
|---|---|---|
| CI no GitHub Actions | Não executado aqui; todos os passos foram corridos localmente | push para a branch → separador Actions |
| `kubectl kustomize` | kubectl indisponível | `kubectl kustomize infra/kubernetes/base` |
| Perfis orchestration, knowledge, observability e analytics | Configuração validada (`docker compose config`), mas não arrancados nem integrados | `python scripts/dev.py start-full` |
| Imagem MinIO | Recusada pelo registry e pelo proxy (ADR-0004) | — |

## Pendente

Ver `docs/architecture/known-gaps.md` (G01–G16). Os mais importantes:
- **G01** — fontes do pacote WE ausentes;
- **G02** — IdP de produção;
- **G05** — motor de workflow (Temporal);
- **G04** — ancoragem externa das cadeias;
- **G03** — Object Lock.

## Decisões necessárias do utilizador

1. Fornecer as duas fontes (ADR-0014).
2. Escolher o IdP de produção e o modelo de claims (ADR-0006).
3. Escolher o fornecedor cloud, a região, o RPO/RTO e o gestor de segredos (não inventados).
4. Validação jurídica de prazos de retenção e da AIPD antes de dados reais.
