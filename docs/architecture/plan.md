# Plano por milestones (Fase 0 → 5) com gates verificáveis

Produzido na Fase 0 (inspeção) e executado na mesma sessão. Resultados em `docs/STATUS.md`.

## Achados da Fase 0
- Repositório praticamente vazio (`README.md` com 10 bytes; um commit). Não havia código, convenções nem cockpit
  a preservar. Não existe modelo `allowed-commands` no repositório.
- **Fontes obrigatórias ausentes** (ADR-0014).
- Ambiente: Docker funcional; imagens pgvector, NATS, Redis e SeaweedFS disponíveis. MinIO indisponível
  (ADR-0004). Proxy com inspeção TLS: os builds usam a CA como BuildKit secret opcional.

## Milestones

| M | Âmbito | Gate (comando) | Critério de aceitação |
|---|---|---|---|
| M1 Fundar | Estrutura, compose core, migrações, tenancy, IAM, Event Store, outbox, auditoria, evidência | `uv run we migrate` (2×) | Base vazia → 9 migrações; 2.ª execução sem alterações; todas as tabelas de domínio com RLS |
| M2 Executável | API, worker, projeções, UI, demo | `python scripts/dev.py demo` | 14 passos OK em processos locais **e** em contentores |
| M3 Conhecimento | Manifesto, registo de fontes, importador validado, staging | `pytest -k knowledge`; `we seed-demo` (2×) | Depósito inválido em quarentena; segredos descartados; seed idempotente |
| M4 Endurecer | Testes adversariais, scans, CI, backup/restore | `pytest tests`; gitleaks; pip-audit; pnpm audit; trivy; syft | 0 segredos; 0 vulnerabilidades conhecidas nas dependências; 0 CRITICAL nas imagens; restore com cadeias verificadas |
| M5 Rever | Revisão independente; STATUS, RESUME, rastreabilidade | revisão + `verify` | Achados corrigidos ou registados em `known-gaps.md` |

## Fora de âmbito (§23 do prompt)
Migração integral de tabelas; ligação a bases ou portais reais; credenciais reais; submissões AT/SS; faturação
certificada; ledger nativo; deployment público; escolha de cloud; microserviços.
