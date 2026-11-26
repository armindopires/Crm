# CLAUDE.md — Wolf Enterprise

Documentação, mensagens funcionais e UI em **PT-PT**. Código e contratos em inglês.

## Comandos
- `python scripts/dev.py bootstrap | start [perfis] | stop | demo | verify`
- `uv run --frozen pytest tests/unit -q` · `tests/contract` · `tests/integration -m integration` (requer `start`)
- `uv run --frozen ruff format src tests scripts && uv run --frozen ruff check src tests scripts && uv run --frozen mypy`
- `pnpm -r typecheck` · `pnpm --filter @we/web build`
- Contratos alterados (rotas ou modelos): `python scripts/dev.py contracts`. O teste de contrato falha se o
  OpenAPI, o AsyncAPI ou o SDK estiverem desatualizados.

## Regras não óbvias
- **Migrações aplicadas são imutáveis** (checksum). Corrigir com um ficheiro novo `db/migrations/NNNN_*.sql`.
- Tabela de domínio nova: `tenant_id NOT NULL`, `UNIQUE (tenant_id, id)`, FKs compostas,
  `platform.enable_tenant_rls(...)`, `make_append_only(...)` se for histórica, GRANT mínimo a `we_app`.
- Acesso a dados só dentro de `db.tenant_tx(tenant_id)`. Nunca definir `we.tenant_id` fora de transação.
- Alteração material = estado + `events.store.append` + `audit.log.record` **na mesma transação**.
- Evento novo: schema em `contracts/jsonschema/events/<tipo>.v<N>.schema.json` com
  `additionalProperties: false` e **sem PII**. Evolução só aditiva.
- Decisões: a IA nunca aprova nem executa. A aprovação exige humano e não pode ser do proponente (há trigger na
  BD). A execução é `recorded_only`.
- Proibido: segredos ou PII reais em seeds e fixtures (usar `.invalid`); executar utilitários DBISAM; ligar a
  bases legadas reais; submissões AT/SS; inventar fornecedor cloud.
- Fontes do pacote WE estão ausentes (ADR-0014). Tratar como `NAO_INDICADO` e não inventar.

## Skills
`.claude/skills/we-new-bounded-context`, `.claude/skills/we-legacy-intake`.
