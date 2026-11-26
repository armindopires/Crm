# DLQ e replay de projeções

## DLQ
- Mensagens passam a `dead` após 8 tentativas (backoff exponencial até 300 s). Métrica: `we_outbox_dlq`.
- Diagnóstico: `SELECT event_id, attempts, last_error FROM event_store.outbox WHERE status='dead'` (admin).
- Corrigida a causa, repor por tenant (ação auditada): `POST /v1/admin/outbox/requeue-dead` (papel
  `tenant_admin`, humano).
- A republicação é segura: JetStream deduplica por `event_id` e os consumidores são idempotentes.

## Replay
- `POST /v1/admin/projections/entity_summary/replay` ou `uv run we replay --tenant <uuid>`.
- O replay reconstrói duas vezes e compara digests (`deterministic`) e compara com a projeção viva
  (`matches_live`). `matches_live=false` com `deterministic=true` indica que a projeção viva estava corrompida
  ou atrasada: o replay corrige.
