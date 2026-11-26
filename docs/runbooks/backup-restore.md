# Backup e restore

## Backup lógico (diário; também antes de qualquer migração)
```bash
docker compose -f infra/compose/compose.yaml --env-file .env exec -T postgres \
  pg_dump -U we_admin -d we -Fc --no-owner > backups/we-$(date -u +%Y%m%dT%H%M%SZ).dump
sha256sum backups/*.dump > backups/SHA256SUMS
```
Objetos S3: replicação do bucket `we-evidence`. Em produção, versionamento + Object Lock + cópia noutra região
(fornecedor NAO_INDICADO).

## Restore (base nova)
```bash
docker compose … exec -T postgres createdb -U we_admin we_restore
docker compose … exec -T postgres pg_restore -U we_admin -d we_restore --no-owner < backups/<ficheiro>.dump
```
Depois do restore é **obrigatório** verificar as cadeias de cada tenant (`we verify-chains --tenant …`) e
reconstruir as projeções (`we replay --tenant …`). O NATS não precisa de restore: a outbox republica o que
estiver `pending`, e o resto é reconstruível.

Prova realizada nesta entrega: ver `docs/STATUS.md` (dump → restore numa base nova → contagens e cadeias
verificadas).

RPO/RTO alvo: **NAO_INDICADO** (decisão de negócio). Proposta inicial: RPO 24 h (dump) / 1 h (WAL archiving),
RTO 4 h.
