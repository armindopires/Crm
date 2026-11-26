# Wolf Enterprise (WE) — núcleo fundacional

A WE é um **Sistema Operacional Cognitivo Organizacional Contextual**: entidades, relações, contexto, eventos,
evidências e decisões governadas, ao serviço de um gabinete de contabilidade e dos seus clientes.
Este repositório contém a **primeira versão executável** do núcleo: um modular monolith event-driven com
PostgreSQL como fonte de verdade.

> Estado: **fundação de desenvolvimento**. Não está *production-ready*. Não tem certificação AT nem
> conformidade normativa completa. Ver [`docs/STATUS.md`](docs/STATUS.md).

## Quick start

Requisitos: Docker + Compose v2, [uv](https://docs.astral.sh/uv/) ≥ 0.7, Python ≥ 3.12. Para a web fora de
contentores: Node 22 + pnpm 10.

```bash
python scripts/dev.py bootstrap         # .env com segredos aleatórios locais + chaves dev em .local/
python scripts/dev.py start             # perfil core: PostgreSQL/pgvector, NATS, Redis, S3, migrações, API, worker
python scripts/dev.py demo              # demonstração vertical E2E (14 passos, dados sintéticos)
python scripts/dev.py start core ui     # + consola operacional em http://localhost:3000
```

API: <http://localhost:8000/docs> · Saúde: `/health/live`, `/health/ready` · Métricas: `/metrics`,
`localhost:9101/metrics` (worker).

## Comandos

| Objetivo | Comando |
|---|---|
| Migrações | `python scripts/dev.py migrate` (`uv run we migrate`) |
| Seed sintético + conhecimento | `python scripts/dev.py seed` |
| Lint / typecheck | `python scripts/dev.py lint` · `python scripts/dev.py typecheck` |
| Testes | `test-unit` · `test-integration` (requer core) · `test-contract` |
| Contratos + SDK | `python scripts/dev.py contracts` |
| Tudo | `python scripts/dev.py verify` |
| Parar / reset local | `python scripts/dev.py stop` · `python scripts/dev.py reset` (confirmação escrita) |
| Integridade | `uv run we verify-chains --tenant <uuid>` · `uv run we verify-evidence --tenant <uuid>` |
| Manifesto de fontes | `uv run we source-manifest` |

## Estrutura

```text
src/we_core/          bounded contexts (platform, identity, kernel, events, evidence, audit, governance,
                      ai, intelligence, knowledge, legacy, workflow, obligations, communications, connectors)
                      + api/ (FastAPI) + worker/ (outbox e projeções) + cli.py
db/migrations/        SQL versionado com checksum (RLS, append-only, triggers de governação)
db/seeds/             apenas dados sintéticos
contracts/            OpenAPI (exportado) · AsyncAPI · JSON Schema de eventos
apps/web/             consola operacional Next.js (PT-PT)
packages/sdk-typescript/  SDK gerado do OpenAPI
infra/                compose por perfis · Dockerfiles · observabilidade · base Kubernetes
docs/                 arquitetura · ADR · segurança · runbooks · STATUS · RESUME
tests/                unit · integration (adversariais) · contract
```

## Documentação essencial

- Arquitetura: [`docs/architecture/`](docs/architecture/) (contexto, contentores, modelo de dados e eventos,
  rastreabilidade, lacunas)
- Decisões: [`docs/adr/`](docs/adr/)
- Segurança: [`docs/security/threat-model.md`](docs/security/threat-model.md),
  [`data-classification.md`](docs/security/data-classification.md)
- Operação: [`docs/runbooks/`](docs/runbooks/)
- Continuação: [`docs/RESUME.md`](docs/RESUME.md)
