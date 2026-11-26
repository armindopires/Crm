-- WE · 0002 · Event Store (fonte de verdade), transactional outbox e projeções reconstruíveis.

CREATE TABLE event_store.events (
  event_id          uuid PRIMARY KEY,
  tenant_id         uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  organization_id   uuid,
  chain_seq         bigint NOT NULL CHECK (chain_seq > 0),
  event_type        text NOT NULL CHECK (event_type ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$'),
  schema_version    int NOT NULL CHECK (schema_version > 0),
  aggregate_type    text NOT NULL,
  aggregate_id      uuid NOT NULL,
  aggregate_version int NOT NULL CHECK (aggregate_version > 0),
  context_frame_id  uuid,
  actor_id          uuid,
  actor_type        text NOT NULL CHECK (actor_type IN ('human','service','ai_agent','system')),
  occurred_at       timestamptz NOT NULL,
  recorded_at       timestamptz NOT NULL,
  correlation_id    uuid NOT NULL,
  causation_id      uuid,
  trace_id          text,
  idempotency_key   text,
  classification    text NOT NULL DEFAULT 'internal'
                    CHECK (classification IN ('public','internal','confidential','restricted','secret')),
  payload           jsonb NOT NULL,
  metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
  previous_hash     text NOT NULL,
  event_hash        text NOT NULL,
  UNIQUE (tenant_id, event_id),
  UNIQUE (tenant_id, chain_seq),
  -- concorrência otimista por agregado
  UNIQUE (tenant_id, aggregate_type, aggregate_id, aggregate_version),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES platform.organizations(tenant_id, organization_id),
  FOREIGN KEY (tenant_id, context_frame_id) REFERENCES kernel.context_frames(tenant_id, context_frame_id)
);
CREATE UNIQUE INDEX events_idempotency ON event_store.events (tenant_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE INDEX events_correlation ON event_store.events (tenant_id, correlation_id);
CREATE INDEX events_aggregate ON event_store.events (tenant_id, aggregate_type, aggregate_id);
SELECT platform.enable_tenant_rls('event_store.events');
SELECT platform.make_append_only('event_store.events');
GRANT SELECT, INSERT ON event_store.events TO we_app;
GRANT SELECT ON event_store.events TO we_worker;
CREATE POLICY worker_read ON event_store.events FOR SELECT TO we_worker USING (true);

-- Transactional outbox: escrita na mesma transação do evento; publicação assíncrona at-least-once.
CREATE TABLE event_store.outbox (
  event_id        uuid PRIMARY KEY,
  tenant_id       uuid NOT NULL,
  subject         text NOT NULL,
  status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','published','dead')),
  attempts        int NOT NULL DEFAULT 0,
  next_attempt_at timestamptz NOT NULL DEFAULT now(),
  last_error      text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  published_at    timestamptz,
  FOREIGN KEY (tenant_id, event_id) REFERENCES event_store.events(tenant_id, event_id)
);
CREATE INDEX outbox_pending ON event_store.outbox (next_attempt_at) WHERE status = 'pending';
SELECT platform.enable_tenant_rls('event_store.outbox');
GRANT SELECT, INSERT ON event_store.outbox TO we_app;
-- reprocessamento de DLQ é ato administrativo auditado, feito pela API dentro do tenant
GRANT UPDATE (status, attempts, next_attempt_at, last_error) ON event_store.outbox TO we_app;
GRANT SELECT, UPDATE ON event_store.outbox TO we_worker;
CREATE POLICY worker_all ON event_store.outbox TO we_worker USING (true) WITH CHECK (true);

-- ─────────── Projeções (descartáveis; reconstruídas por replay a partir do Event Store) ───────────
CREATE TABLE projection.entity_summary (
  tenant_id              uuid NOT NULL,
  entity_id              uuid NOT NULL,
  entity_type            text,
  display_name           text,
  event_count            int NOT NULL DEFAULT 0,
  last_event_type        text NOT NULL,
  last_aggregate_version int NOT NULL,
  last_chain_seq         bigint NOT NULL,
  last_event_at          timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, entity_id)
);
CREATE TABLE projection.checkpoints (
  tenant_id       uuid NOT NULL,
  projection_name text NOT NULL,
  last_chain_seq  bigint NOT NULL DEFAULT 0,
  updated_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, projection_name)
);
CREATE TABLE projection.processed_events (
  tenant_id       uuid NOT NULL,
  projection_name text NOT NULL,
  event_id        uuid NOT NULL,
  processed_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, projection_name, event_id)
);
SELECT platform.enable_tenant_rls('projection.entity_summary');
SELECT platform.enable_tenant_rls('projection.checkpoints');
SELECT platform.enable_tenant_rls('projection.processed_events');
GRANT SELECT, INSERT, UPDATE, DELETE ON projection.entity_summary, projection.checkpoints,
  projection.processed_events TO we_app, we_worker;
