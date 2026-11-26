# Recuperação de desastre

1. Provisionar um ambiente novo (compose ou cluster). As imagens OCI são reproduzíveis a partir do Git e dos
   lockfiles.
2. Restaurar o PostgreSQL (backup-restore.md) e o bucket de evidências.
3. `uv run we migrate` (só aplica o que faltar; os checksums validam a coerência).
4. Por tenant: `we verify-chains`, `we verify-evidence`, `we replay`.
5. Arrancar o worker: a outbox `pending` republica, e o NATS é reconstruído a partir do PostgreSQL.
6. Registar uma DECISION de recuperação com evidências (relatórios de verificação).

Fornecedor cloud, região e RPO/RTO: **NAO_INDICADO**. Não foi inventado Terraform (ver STATUS).
