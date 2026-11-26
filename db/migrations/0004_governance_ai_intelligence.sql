-- WE · 0004 · Governance (DECISION + aprovação humana), AI_TRACE e Intelligence (SIGNAL → OPPORTUNITY).

CREATE TABLE ai.ai_traces (
  ai_trace_id        uuid PRIMARY KEY,
  tenant_id          uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  provider           text NOT NULL,
  model              text NOT NULL,
  capability         text NOT NULL,
  prompt_template_id text NOT NULL,
  prompt_version     text NOT NULL,
  input_hash         text NOT NULL,
  output_hash        text NOT NULL,
  input_ref          text,                     -- referência segura/redigida, nunca dados restritos em claro
  output_summary     text,
  tools_called       jsonb NOT NULL DEFAULT '[]'::jsonb,
  parameters         jsonb NOT NULL DEFAULT '{}'::jsonb,
  tokens_in          int,
  tokens_out         int,
  cost_amount        numeric(18,6),
  cost_currency      char(3),
  policy_refs        jsonb NOT NULL DEFAULT '[]'::jsonb,
  side_effects       text NOT NULL DEFAULT 'blocked' CHECK (side_effects IN ('blocked','none')),
  requested_by       uuid NOT NULL,
  correlation_id     uuid NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, ai_trace_id),
  FOREIGN KEY (tenant_id, requested_by) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('ai.ai_traces');
SELECT platform.make_append_only('ai.ai_traces');
GRANT SELECT, INSERT ON ai.ai_traces TO we_app;

CREATE TABLE governance.decisions (
  decision_id      uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  organization_id  uuid,
  title            text NOT NULL,
  description      text,
  decision_type    text NOT NULL,
  impact_category  text NOT NULL CHECK (impact_category IN
                   ('juridico','fiscal','financeiro','laboral','reputacional','externo','interno')),
  requires_human_approval boolean NOT NULL DEFAULT true,
  status           text NOT NULL DEFAULT 'proposed' CHECK (status IN
                   ('proposed','under_review','approved','rejected','executed','superseded')),
  context_frame_id uuid NOT NULL,
  proposed_by      uuid NOT NULL,
  proposed_by_type text NOT NULL CHECK (proposed_by_type IN ('human','service','ai_agent')),
  ai_trace_id      uuid,
  decided_by       uuid,
  decided_at       timestamptz,
  rationale        text,
  executed_by      uuid,
  executed_at      timestamptz,
  superseded_by    uuid,
  version          int NOT NULL DEFAULT 1,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, decision_id),
  -- impacto material exige sempre aprovação humana
  CHECK (requires_human_approval OR impact_category = 'interno'),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES platform.organizations(tenant_id, organization_id),
  FOREIGN KEY (tenant_id, context_frame_id) REFERENCES kernel.context_frames(tenant_id, context_frame_id),
  FOREIGN KEY (tenant_id, proposed_by) REFERENCES iam.actors(tenant_id, actor_id),
  FOREIGN KEY (tenant_id, decided_by) REFERENCES iam.actors(tenant_id, actor_id),
  FOREIGN KEY (tenant_id, executed_by) REFERENCES iam.actors(tenant_id, actor_id),
  FOREIGN KEY (tenant_id, ai_trace_id) REFERENCES ai.ai_traces(tenant_id, ai_trace_id)
);
SELECT platform.enable_tenant_rls('governance.decisions');
GRANT SELECT, INSERT, UPDATE ON governance.decisions TO we_app;

-- Guarda de máquina de estados ao nível da base de dados (defesa em profundidade face à API).
CREATE OR REPLACE FUNCTION governance.guard_decision_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  allowed boolean;
  approver_type text;
BEGIN
  IF NEW.decision_id <> OLD.decision_id OR NEW.tenant_id <> OLD.tenant_id
     OR NEW.context_frame_id <> OLD.context_frame_id OR NEW.proposed_by <> OLD.proposed_by THEN
    RAISE EXCEPTION 'WE-DECISION-IMMUTABLE: campos de identidade/contexto não podem mudar';
  END IF;
  IF NEW.status = OLD.status THEN
    RAISE EXCEPTION 'WE-DECISION-NOOP: transição sem mudança de estado';
  END IF;
  allowed := (OLD.status, NEW.status) IN (
    ('proposed','under_review'), ('proposed','approved'), ('proposed','rejected'),
    ('under_review','approved'), ('under_review','rejected'),
    ('approved','executed'), ('approved','superseded'), ('executed','superseded'),
    ('proposed','superseded'), ('under_review','superseded'));
  IF NOT allowed THEN
    RAISE EXCEPTION 'WE-DECISION-TRANSITION: % -> % não permitido', OLD.status, NEW.status;
  END IF;
  IF NEW.status IN ('approved','rejected') THEN
    IF NEW.decided_by IS NULL OR NEW.decided_at IS NULL THEN
      RAISE EXCEPTION 'WE-DECISION-APPROVER: aprovação/rejeição exige decisor identificado';
    END IF;
    IF NEW.decided_by = OLD.proposed_by THEN
      RAISE EXCEPTION 'WE-DECISION-SOD: o proponente não pode aprovar a própria proposta';
    END IF;
    SELECT actor_type INTO approver_type FROM iam.actors
      WHERE tenant_id = NEW.tenant_id AND actor_id = NEW.decided_by;
    IF NEW.requires_human_approval AND approver_type IS DISTINCT FROM 'human' THEN
      RAISE EXCEPTION 'WE-DECISION-HITL: aprovação exige ator humano';
    END IF;
  END IF;
  IF NEW.status = 'executed' AND (NEW.executed_by IS NULL OR NEW.executed_at IS NULL) THEN
    RAISE EXCEPTION 'WE-DECISION-EXEC: execução exige executor identificado';
  END IF;
  NEW.version := OLD.version + 1;
  NEW.updated_at := now();
  RETURN NEW;
END $$;
CREATE TRIGGER decision_transition BEFORE UPDATE ON governance.decisions
  FOR EACH ROW EXECUTE FUNCTION governance.guard_decision_transition();
CREATE TRIGGER decision_no_delete BEFORE DELETE ON governance.decisions
  FOR EACH ROW EXECUTE FUNCTION platform.forbid_mutation();

CREATE TABLE governance.approvals (
  approval_id uuid PRIMARY KEY,
  tenant_id   uuid NOT NULL,
  decision_id uuid NOT NULL,
  approver_id uuid NOT NULL,
  verdict     text NOT NULL CHECK (verdict IN ('approved','rejected')),
  rationale   text NOT NULL CHECK (length(rationale) >= 3),
  created_at  timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, decision_id) REFERENCES governance.decisions(tenant_id, decision_id),
  FOREIGN KEY (tenant_id, approver_id) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('governance.approvals');
SELECT platform.make_append_only('governance.approvals');
GRANT SELECT, INSERT ON governance.approvals TO we_app;

CREATE TABLE intelligence.signals (
  signal_id        uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  organization_id  uuid,
  signal_type      text NOT NULL,
  source           text NOT NULL,
  strength         numeric(5,4) NOT NULL CHECK (strength >= 0 AND strength <= 1),
  entity_id        uuid,
  context_frame_id uuid,
  description      text NOT NULL,
  status           text NOT NULL DEFAULT 'new' CHECK (status IN ('new','triaged','promoted','dismissed')),
  created_by       uuid NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  version          int NOT NULL DEFAULT 1,
  UNIQUE (tenant_id, signal_id),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES platform.organizations(tenant_id, organization_id),
  FOREIGN KEY (tenant_id, entity_id) REFERENCES kernel.entities(tenant_id, entity_id),
  FOREIGN KEY (tenant_id, context_frame_id) REFERENCES kernel.context_frames(tenant_id, context_frame_id),
  FOREIGN KEY (tenant_id, created_by) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('intelligence.signals');
GRANT SELECT, INSERT, UPDATE (status, version) ON intelligence.signals TO we_app;

CREATE TABLE intelligence.opportunities (
  opportunity_id  uuid PRIMARY KEY,
  tenant_id       uuid NOT NULL,
  signal_id       uuid NOT NULL,
  title           text NOT NULL,
  value_estimate  numeric(18,2),
  currency        char(3) CHECK (currency ~ '^[A-Z]{3}$'),
  status          text NOT NULL DEFAULT 'identified'
                  CHECK (status IN ('identified','qualified','pursuing','won','lost','discarded')),
  owner_actor_id  uuid NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, opportunity_id),
  UNIQUE (tenant_id, signal_id),
  CHECK ((value_estimate IS NULL) = (currency IS NULL)),
  FOREIGN KEY (tenant_id, signal_id) REFERENCES intelligence.signals(tenant_id, signal_id),
  FOREIGN KEY (tenant_id, owner_actor_id) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('intelligence.opportunities');
GRANT SELECT, INSERT, UPDATE (status) ON intelligence.opportunities TO we_app;
