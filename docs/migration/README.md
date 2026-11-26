# Migração e integração de legados

- Estratégia e regras: [`../runbooks/migracao-legado.md`](../runbooks/migracao-legado.md), ADR-0012, ADR-0014.
- Esquema: `legacy.*` (migração 0006). Sistemas registados: migração 0007.
- Fase 1 contabilística: a Filosoft mantém-se como system of record. A WE recebe read models com chave
  `(entidade, exercício, período, fonte)`. O ledger nativo fica num roadmap separado.
- Inventário de tabelas (CrmContab 218, 780 no total): **não realizado**, porque as fontes estão ausentes.
