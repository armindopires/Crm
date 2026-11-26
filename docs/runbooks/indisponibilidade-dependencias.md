# Indisponibilidade de dependências

| Dependência | Sintoma | Efeito | Ação |
|---|---|---|---|
| PostgreSQL | `/health/ready` 503 (`postgres: fail`) | API indisponível; nada se perde | Ver `docker compose logs postgres`; espaço em disco; restore se houver corrupção |
| NATS | Worker `healthz` 503; `we_outbox_pending` a crescer | Escritas continuam (outbox); projeções atrasam | Repor NATS; o worker drena a outbox por ordem; verificar `we_outbox_dlq` |
| Armazenamento S3 | Ready 503 (`object_storage: fail`); uploads 5xx | Sem novas evidências; o resto funciona | Repor serviço; `we verify-evidence --tenant …` |
| Redis | Ready `degraded` | Rate limiting desativado (fail-open) | Repor Redis; vigiar abuso (`we_http_requests_total`) |

Após recuperação: `GET /v1/admin/outbox` (pendentes → 0, `projection_lag.lag` → 0).
