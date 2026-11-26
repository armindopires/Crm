# ADR-0009 — EventBus NATS JetStream, outbox com lease de publicador único, Redis em fail-open

- **Estado:** aprovado · **Evidência:** DECISAO_APROVADA (NATS inicial, Kafka futura) + PROPOSTA_TECNICA

## Decisão
- A porta `EventBus` (`we_core/events/bus.py`) tem implementações NATS JetStream e em memória (testes).
  Kafka será um adaptador futuro, e nunca corre em simultâneo com o NATS.
- Stream `WE_EVENTS`, subjects `we.<tenant>.<event_type>`, `Nats-Msg-Id = event_id` (janela de deduplicação de
  10 min).
- **Sem promessa de exactly-once**: a entrega é at-least-once e os consumidores são idempotentes
  (`processed_events`).
- Publicador: `SELECT … FOR UPDATE SKIP LOCKED` ordenado por `(tenant, chain_seq)`, com retry e backoff
  exponencial (máx. 300 s). Ao fim de 8 tentativas a mensagem passa a `dead` (DLQ), com reposição auditada
  (`POST /v1/admin/outbox/requeue-dead`).
- **Lease de publicador único** (`pg_try_advisory_xact_lock`): com várias réplicas, só uma publica em cada ciclo
  e a ordem por tenant fica preservada.
- O Redis serve só para rate limiting por tenant (janela fixa por minuto). Se o Redis estiver em baixo, o rate
  limiting entra em **fail-open**, sinalizado como `degraded` em `/health/ready`. Decisão consciente entre
  disponibilidade e proteção. Rever antes de expor a API publicamente.
