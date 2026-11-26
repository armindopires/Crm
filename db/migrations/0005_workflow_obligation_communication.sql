-- WE · 0005 · Procedural Runtime (definições versionadas), Obligations & Compliance, Communications.

CREATE TABLE workflow.definitions (
  definition_id uuid PRIMARY KEY,
  tenant_id     uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  key           text NOT NULL CHECK (key ~ '^[a-z][a-z0-9_.-]{1,62}$'),
  version       int NOT NULL CHECK (version > 0),
  title_pt      text NOT NULL,
  spec          jsonb NOT NULL,           -- MACROPROCESS→PROCESS→…→CHECKPOINT→EVIDENCE→DECISION→VALUE
  spec_hash     text NOT NULL,
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','retired')),
  created_by    uuid NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, definition_id),
  UNIQUE (tenant_id, key, version),
  FOREIGN KEY (tenant_id, created_by) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('workflow.definitions');
SELECT platform.make_append_only('workflow.definitions');
GRANT SELECT, INSERT ON workflow.definitions TO we_app;

CREATE TABLE workflow.instances (
  instance_id      uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL,
  definition_id    uuid NOT NULL,             -- versão fixada no arranque
  status           text NOT NULL DEFAULT 'running'
                   CHECK (status IN ('running','paused','waiting_approval','completed','failed','compensated','cancelled')),
  current_step     text,
  context_frame_id uuid NOT NULL,
  engine           text NOT NULL DEFAULT 'local' CHECK (engine IN ('local','temporal')),
  engine_ref       text,
  started_by       uuid NOT NULL,
  started_at       timestamptz NOT NULL DEFAULT now(),
  completed_at     timestamptz,
  version          int NOT NULL DEFAULT 1,
  UNIQUE (tenant_id, instance_id),
  FOREIGN KEY (tenant_id, definition_id) REFERENCES workflow.definitions(tenant_id, definition_id),
  FOREIGN KEY (tenant_id, context_frame_id) REFERENCES kernel.context_frames(tenant_id, context_frame_id),
  FOREIGN KEY (tenant_id, started_by) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('workflow.instances');
GRANT SELECT, INSERT, UPDATE (status, current_step, completed_at, version, engine_ref) ON workflow.instances TO we_app;

CREATE TABLE workflow.step_log (
  step_log_id  uuid PRIMARY KEY,
  tenant_id    uuid NOT NULL,
  instance_id  uuid NOT NULL,
  level        text NOT NULL CHECK (level IN ('MACROPROCESS','PROCESS','SUBPROCESS','FLOW','STEP','MICROSTEP',
                                             'CHECKPOINT','EVIDENCE','DECISION','VALUE_GENERATED')),
  step_key     text NOT NULL,
  status       text NOT NULL CHECK (status IN ('started','completed','failed','retried','compensated','timed_out','waiting_approval')),
  actor_id     uuid,
  evidence_id  uuid,
  decision_id  uuid,
  details      jsonb NOT NULL DEFAULT '{}'::jsonb,
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, instance_id) REFERENCES workflow.instances(tenant_id, instance_id),
  FOREIGN KEY (tenant_id, evidence_id) REFERENCES evidence.evidence(tenant_id, evidence_id),
  FOREIGN KEY (tenant_id, decision_id) REFERENCES governance.decisions(tenant_id, decision_id)
);
SELECT platform.enable_tenant_rls('workflow.step_log');
SELECT platform.make_append_only('workflow.step_log');
GRANT SELECT, INSERT ON workflow.step_log TO we_app;

-- Catálogo global de regras normativas (aprovado como não-tenant). Nunca ativo em produção sem validação externa.
CREATE TABLE obligation.rule_catalog (
  rule_id           uuid PRIMARY KEY,
  rule_code         text NOT NULL,
  version           int NOT NULL CHECK (version > 0),
  jurisdiction      text NOT NULL,
  title_pt          text NOT NULL,
  effective_from    date NOT NULL,
  effective_to      date,
  rule_spec         jsonb NOT NULL,          -- DSL controlada; sem lógica anual em código rígido
  source_ref        text NOT NULL,
  source_url        text,
  source_version    text,
  source_hash       text,
  validated_at      timestamptz,
  validation_status text NOT NULL DEFAULT 'VALIDACAO_EXTERNA_PENDENTE'
                    CHECK (validation_status IN ('VALIDACAO_EXTERNA_PENDENTE','VALIDADO','DESATUALIZADO')),
  production_enabled boolean NOT NULL DEFAULT false,
  UNIQUE (rule_code, version),
  CHECK (effective_to IS NULL OR effective_to >= effective_from),
  CHECK (NOT production_enabled OR (validation_status = 'VALIDADO' AND source_url IS NOT NULL AND source_hash IS NOT NULL))
);
GRANT SELECT ON obligation.rule_catalog TO we_app;

CREATE TABLE obligation.obligations (
  obligation_id         uuid PRIMARY KEY,
  tenant_id             uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  rule_id               uuid NOT NULL REFERENCES obligation.rule_catalog(rule_id),
  responsible_entity_id uuid NOT NULL,
  fiscal_year           int,
  period_code           text,
  due_date              date NOT NULL,
  status                text NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open','in_progress','ready_for_review','fulfilled_manually','overdue','cancelled')),
  required_evidence     jsonb NOT NULL DEFAULT '[]'::jsonb,
  depends_on            uuid[] NOT NULL DEFAULT '{}',
  created_at            timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, obligation_id),
  FOREIGN KEY (tenant_id, responsible_entity_id) REFERENCES kernel.entities(tenant_id, entity_id)
);
SELECT platform.enable_tenant_rls('obligation.obligations');
GRANT SELECT, INSERT, UPDATE (status) ON obligation.obligations TO we_app;

-- COMMUNICATION_EVENT / INTERACTION: registo apenas; envio externo bloqueado nesta fase.
CREATE TABLE communication.communication_events (
  communication_event_id uuid PRIMARY KEY,
  tenant_id     uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  channel       text NOT NULL CHECK (channel IN ('email','phone','meeting','portal','letter','chat','other')),
  direction     text NOT NULL CHECK (direction IN ('inbound','outbound','internal')),
  entity_id     uuid,
  subject_ref   text,
  content_evidence_id uuid,
  classification text NOT NULL DEFAULT 'confidential',
  delivery_status text NOT NULL DEFAULT 'recorded_only' CHECK (delivery_status IN ('recorded_only','draft')),
  occurred_at   timestamptz NOT NULL,
  created_by    uuid NOT NULL,
  UNIQUE (tenant_id, communication_event_id),
  FOREIGN KEY (tenant_id, entity_id) REFERENCES kernel.entities(tenant_id, entity_id),
  FOREIGN KEY (tenant_id, content_evidence_id) REFERENCES evidence.evidence(tenant_id, evidence_id),
  FOREIGN KEY (tenant_id, created_by) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('communication.communication_events');
SELECT platform.make_append_only('communication.communication_events');
GRANT SELECT, INSERT ON communication.communication_events TO we_app;

CREATE TABLE communication.interactions (
  interaction_id uuid PRIMARY KEY,
  tenant_id      uuid NOT NULL,
  communication_event_id uuid NOT NULL,
  actor_id       uuid,
  entity_id      uuid,
  interaction_type text NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, communication_event_id)
    REFERENCES communication.communication_events(tenant_id, communication_event_id),
  FOREIGN KEY (tenant_id, entity_id) REFERENCES kernel.entities(tenant_id, entity_id)
);
SELECT platform.enable_tenant_rls('communication.interactions');
SELECT platform.make_append_only('communication.interactions');
GRANT SELECT, INSERT ON communication.interactions TO we_app;
