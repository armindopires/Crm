# ADR-0003 — Multi-tenancy: tenant_id + FKs compostas + RLS FORCE deny-by-default

- **Estado:** aprovado · **Evidência:** DECISAO_APROVADA (§11) + PROPOSTA_TECNICA (mecanismo)

## Decisão
1. `tenant_id NOT NULL` em todas as tabelas de domínio. As exceções são os catálogos globais aprovados:
   `platform.capabilities`, `legacy.source_systems` e `obligation.rule_catalog`.
2. `UNIQUE (tenant_id, id)` e **FKs compostas** `(tenant_id, x_id)`: uma referência a outro tenant é impossível
   mesmo contornando a API (provado em `tests/integration/test_isolation_and_integrity.py`).
3. **RLS `ENABLE` + `FORCE`** com política `tenant_id = platform.current_tenant()` em `USING` e `WITH CHECK`.
   Sem contexto, nenhuma linha é visível.
4. O contexto é definido por `set_config('we.tenant_id', …, is_local => true)` dentro de uma transação
   explícita por pedido (`Database.tenant_tx`). Não sobrevive ao fim da transação, o que evita fugas em
   connection pools (há teste).
5. O tenant vem **só** da claim assinada `we_tenant_id`, validada contra `iam.actors` e `iam.memberships`.
   Nenhum header livre é aceite.
6. Os roles aplicacionais `we_app` e `we_worker` são `NOBYPASSRLS` e não são owners. As migrações correm com
   `we_admin`.
7. Um recurso de outro tenant responde **404** (não 403), para evitar enumeração.

## Riscos residuais
- `we_worker` tem políticas `worker_all` na outbox e leitura global de eventos (necessário para o publicador).
  Mitigação: role sem acesso a outros schemas e credencial própria.
- Um DBA ou superuser contorna a RLS. Mitigação: cadeias de hash detetam adulteração (ADR-0007) e o acesso
  de DBA deve ser auditado na plataforma (pendente).
