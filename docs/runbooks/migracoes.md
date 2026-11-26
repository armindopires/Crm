# Migrações

- Aplicar: `uv run we migrate` (ou o job `migrate` do compose). Estado: `uv run we migration-status`.
- Uma migração aplicada **nunca** se edita. O checksum é verificado e o arranque falha. Correções entram num
  ficheiro novo `NNNN_descricao.sql`.
- Cada ficheiro corre numa transação. Um advisory lock impede execuções concorrentes.
- Checklist de uma migração nova: `tenant_id NOT NULL`; `UNIQUE (tenant_id, id)`; FKs compostas;
  `SELECT platform.enable_tenant_rls('schema.tabela')`; `make_append_only` se for histórico; GRANT mínimo a
  `we_app`; testar numa base vazia **e** numa base com dados.
- Rollback: lógico, por nova migração. Numa falha destrutiva, restore (backup-restore.md).
