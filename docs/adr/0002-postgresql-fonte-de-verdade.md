# ADR-0002 — PostgreSQL como fonte de verdade: estado + Event Store + outbox na mesma transação

- **Estado:** aprovado · **Evidência:** DECISAO_APROVADA (PostgreSQL é o destino oficial) + PROPOSTA_TECNICA (padrão)

## Decisão
- **Estado atual** em tabelas normalizadas por contexto (por exemplo `kernel.entities`).
- **Event Store** (`event_store.events`): append-only, uma linha por alteração material, com concorrência
  otimista por `(tenant_id, aggregate_type, aggregate_id, aggregate_version)` e idempotência por
  `(tenant_id, idempotency_key)`.
- **Transactional outbox** (`event_store.outbox`) escrita na mesma transação; o worker publica no EventBus.
- NATS, Neo4j, OpenSearch e ClickHouse são **transporte ou projeções** reconstruíveis.

Não se adota event sourcing puro (estado derivado só de eventos) nesta fase. Ficaria mais caro de operar e
pouco útil enquanto a Filosoft continua como system of record contabilístico.

## Consequências
- Replay determinístico apenas das projeções, não do estado transacional. Os eventos registam factos de
  alteração sem PII (ADR-0013), pelo que não chegam para reconstruir estado com dados pessoais. É intencional.
- Entrega at-least-once. Os consumidores são idempotentes (`projection.processed_events`).

## Reversibilidade
Média. A migração para event sourcing pleno exige payloads mais ricos (com cifragem por sujeito e
crypto-shredding).
