---
name: we-new-bounded-context
description: Acrescentar uma capacidade ou bounded context à WE (tabela, serviço, evento, endpoint, testes) respeitando tenancy, RLS, Event Store, auditoria e contratos. Usar sempre que se cria uma tabela de domínio, um evento novo ou um endpoint novo.
---

# Novo bounded context ou capacidade na WE

1. **Migração** `db/migrations/NNNN_<nome>.sql` (nova, nunca editar as aplicadas):
   - `tenant_id uuid NOT NULL REFERENCES platform.tenants`, `UNIQUE (tenant_id, <id>)`;
   - FKs compostas `(tenant_id, x_id) REFERENCES … (tenant_id, x_id)`;
   - `SELECT platform.enable_tenant_rls('schema.tabela');`;
   - histórico → `SELECT platform.make_append_only('schema.tabela');` e só `GRANT SELECT, INSERT`;
   - estado → GRANT `UPDATE` apenas nas colunas necessárias.
2. **Evento**: `contracts/jsonschema/events/<contexto>.<facto_no_passado>.v1.schema.json` com
   `additionalProperties: false`. Só factos e referências, sem valores pessoais.
3. **Serviço** `src/we_core/<contexto>/service.py`: `require(conn, ctx.principal, "<perm>", Resource(...))`,
   depois estado, `append(conn, ctx, EventDraft(...))` e `audit.record(...)`, tudo na mesma `conn`.
   Acrescentar a permissão a `identity/authz.py::ROLE_PERMISSIONS`. Se for um ato humano, a `HUMAN_ONLY`.
4. **API** `src/we_core/api/routers/*.py` + modelos em `api/models.py`. POST com `Idempotency-Key` via
   `run_idempotent`.
5. **Contratos**: `python scripts/dev.py contracts` (OpenAPI, AsyncAPI, SDK).
6. **Testes**: unitário (regras) + integração (isolamento entre tenants, append-only, idempotência).
7. **Docs**: linha na `docs/architecture/traceability-matrix.md`; ADR se houver decisão relevante;
   `docs/STATUS.md`.

Gate: `python scripts/dev.py verify`.
