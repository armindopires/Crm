# ADR-0005 — Migrações SQL versionadas com checksum, sem ORM

- **Estado:** aprovado · **Evidência:** PROPOSTA_TECNICA

## Decisão
`db/migrations/NNNN_*.sql` são aplicadas por `we migrate` (`we_core/migrate.py`), uma transação por ficheiro,
com `public.we_schema_migrations(version, checksum)` e advisory lock. **Uma migração aplicada nunca é editada**:
um checksum diferente faz o arranque falhar. As correções entram numa migração nova (por exemplo 0009).
O acesso a dados usa SQL explícito com psycopg 3 (sem ORM). Políticas RLS, grants e triggers são de primeira
classe e auditáveis em revisão de código.

## Consequências
Sem *down migrations* automáticas. O rollback é lógico, através de nova migração ou restore (runbook).
