-- WE · 0010 · Endurecimento após revisão independente (achados 1, 2, 9, 13).

-- (1) Nenhuma espera indefinida por locks ou consultas longas.
ALTER ROLE we_app SET lock_timeout = '5s';
ALTER ROLE we_app SET statement_timeout = '30s';
ALTER ROLE we_worker SET lock_timeout = '5s';
ALTER ROLE we_worker SET statement_timeout = '60s';

-- (2) Decisões: UPDATE só nas colunas de transição; restantes colunas imutáveis por trigger.
REVOKE UPDATE ON governance.decisions FROM we_app;
GRANT UPDATE (status, decided_by, decided_at, rationale, executed_by, executed_at, superseded_by)
  ON governance.decisions TO we_app;

CREATE OR REPLACE FUNCTION governance.guard_decision_transition() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  allowed boolean;
  approver_type text;
BEGIN
  IF NEW.decision_id <> OLD.decision_id OR NEW.tenant_id <> OLD.tenant_id
     OR NEW.context_frame_id <> OLD.context_frame_id OR NEW.proposed_by <> OLD.proposed_by
     OR NEW.requires_human_approval IS DISTINCT FROM OLD.requires_human_approval
     OR NEW.impact_category IS DISTINCT FROM OLD.impact_category
     OR NEW.proposed_by_type IS DISTINCT FROM OLD.proposed_by_type
     OR NEW.ai_trace_id IS DISTINCT FROM OLD.ai_trace_id
     OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
     OR NEW.title IS DISTINCT FROM OLD.title
     OR NEW.decision_type IS DISTINCT FROM OLD.decision_type
     OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION 'WE-DECISION-IMMUTABLE: campos de identidade/contexto/impacto não podem mudar';
  END IF;
  IF OLD.decided_by IS NOT NULL AND (NEW.decided_by IS DISTINCT FROM OLD.decided_by
                                     OR NEW.decided_at IS DISTINCT FROM OLD.decided_at
                                     OR NEW.rationale IS DISTINCT FROM OLD.rationale) THEN
    RAISE EXCEPTION 'WE-DECISION-IMMUTABLE: decisor e fundamentação não podem ser reescritos';
  END IF;
  IF OLD.executed_by IS NOT NULL AND (NEW.executed_by IS DISTINCT FROM OLD.executed_by
                                      OR NEW.executed_at IS DISTINCT FROM OLD.executed_at) THEN
    RAISE EXCEPTION 'WE-DECISION-IMMUTABLE: execução não pode ser reescrita';
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
    IF NOT EXISTS (SELECT 1 FROM governance.approvals a
                   WHERE a.tenant_id = NEW.tenant_id AND a.decision_id = NEW.decision_id
                     AND a.approver_id = NEW.decided_by AND a.verdict = NEW.status) THEN
      RAISE EXCEPTION 'WE-DECISION-APPROVAL-RECORD: falta registo em governance.approvals';
    END IF;
  END IF;
  IF NEW.status = 'executed' AND (NEW.executed_by IS NULL OR NEW.executed_at IS NULL) THEN
    RAISE EXCEPTION 'WE-DECISION-EXEC: execução exige executor identificado';
  END IF;
  NEW.version := OLD.version + 1;
  NEW.updated_at := now();
  RETURN NEW;
END $$;

-- (13) Atores: tipo e habilitação não podem ser alterados pela aplicação (o HITL depende de actor_type).
REVOKE UPDATE ON iam.actors FROM we_app;
GRANT UPDATE (status, display_name) ON iam.actors TO we_app;
REVOKE UPDATE ON iam.memberships FROM we_app;
GRANT UPDATE (valid_to) ON iam.memberships TO we_app;

-- (9) Idempotência HTTP associada ao ator que fez o pedido original.
ALTER TABLE api.idempotency_keys ADD COLUMN actor_id uuid;
