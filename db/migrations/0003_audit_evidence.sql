-- WE · 0003 · Audit Registry (append-only, cadeia de hashes) e Evidence Engine (imutável, cadeia de custódia).

CREATE TABLE audit.audit_log (
  audit_id         uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  chain_seq        bigint NOT NULL CHECK (chain_seq > 0),
  occurred_at      timestamptz NOT NULL,
  actor_id         uuid,
  actor_type       text NOT NULL CHECK (actor_type IN ('human','service','ai_agent','system')),
  actor_ref        text NOT NULL,            -- pseudónimo HMAC do sujeito IdP (nunca o valor em claro)
  action           text NOT NULL,
  resource_type    text NOT NULL,
  resource_id      text,
  outcome          text NOT NULL CHECK (outcome IN ('allowed','denied','succeeded','failed')),
  reason           text,
  policy_refs      jsonb NOT NULL DEFAULT '[]'::jsonb,
  context_frame_id uuid,
  correlation_id   uuid NOT NULL,
  trace_id         text,
  origin_ref       text,                     -- pseudónimo da origem (IP/cliente)
  details          jsonb NOT NULL DEFAULT '{}'::jsonb,
  previous_hash    text NOT NULL,
  record_hash      text NOT NULL,
  UNIQUE (tenant_id, chain_seq)
);
CREATE INDEX audit_correlation ON audit.audit_log (tenant_id, correlation_id);
SELECT platform.enable_tenant_rls('audit.audit_log');
SELECT platform.make_append_only('audit.audit_log');
GRANT SELECT, INSERT ON audit.audit_log TO we_app;

CREATE TABLE evidence.evidence (
  evidence_id       uuid PRIMARY KEY,
  tenant_id         uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  organization_id   uuid,
  sha256            text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes        bigint NOT NULL CHECK (size_bytes >= 0),
  media_type        text NOT NULL,
  filename_safe     text NOT NULL,
  storage_bucket    text NOT NULL,
  storage_key       text NOT NULL,
  storage_version   text,
  classification    text NOT NULL CHECK (classification IN ('public','internal','confidential','restricted','secret')),
  retention_class   text NOT NULL DEFAULT 'NAO_INDICADO',
  retention_until   date,
  source            text NOT NULL,
  uploaded_by       uuid NOT NULL,
  uploaded_at       timestamptz NOT NULL,
  supersedes_id     uuid,
  metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (tenant_id, evidence_id),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES platform.organizations(tenant_id, organization_id),
  FOREIGN KEY (tenant_id, uploaded_by) REFERENCES iam.actors(tenant_id, actor_id),
  FOREIGN KEY (tenant_id, supersedes_id) REFERENCES evidence.evidence(tenant_id, evidence_id)
);
CREATE INDEX evidence_sha ON evidence.evidence (tenant_id, sha256);
SELECT platform.enable_tenant_rls('evidence.evidence');
SELECT platform.make_append_only('evidence.evidence');
GRANT SELECT, INSERT ON evidence.evidence TO we_app;

CREATE TABLE evidence.custody_events (
  custody_event_id uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL,
  evidence_id      uuid NOT NULL,
  action           text NOT NULL CHECK (action IN ('uploaded','verified','verification_failed','linked','accessed')),
  actor_id         uuid,
  occurred_at      timestamptz NOT NULL DEFAULT now(),
  sha256_observed  text,
  details          jsonb NOT NULL DEFAULT '{}'::jsonb,
  FOREIGN KEY (tenant_id, evidence_id) REFERENCES evidence.evidence(tenant_id, evidence_id)
);
SELECT platform.enable_tenant_rls('evidence.custody_events');
SELECT platform.make_append_only('evidence.custody_events');
GRANT SELECT, INSERT ON evidence.custody_events TO we_app;

-- Ligações tipadas entre evidência e entidade/evento/processo/obrigação/decisão/comunicação.
CREATE TABLE evidence.links (
  link_id     uuid PRIMARY KEY,
  tenant_id   uuid NOT NULL,
  evidence_id uuid NOT NULL,
  target_type text NOT NULL CHECK (target_type IN
               ('entity','event','workflow_instance','obligation','decision','communication','signal','opportunity')),
  target_id   uuid NOT NULL,
  link_type   text NOT NULL DEFAULT 'supports',
  created_by  uuid NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, evidence_id, target_type, target_id, link_type),
  FOREIGN KEY (tenant_id, evidence_id) REFERENCES evidence.evidence(tenant_id, evidence_id)
);
SELECT platform.enable_tenant_rls('evidence.links');
SELECT platform.make_append_only('evidence.links');
GRANT SELECT, INSERT ON evidence.links TO we_app;
