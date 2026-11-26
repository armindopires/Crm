-- WE · 0001 · Foundation: extensões, schemas, roles, funções de suporte, tenancy, IAM e kernel cognitivo.
-- Regras: tenant_id obrigatório; FKs compostas (tenant_id, id); RLS deny-by-default (FORCE);
-- tabelas históricas append-only por privilégio + trigger.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- Roles aplicacionais (sem LOGIN aqui; o comando `we migrate` ativa LOGIN e password a partir do ambiente).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'we_app') THEN
    CREATE ROLE we_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'we_worker') THEN
    CREATE ROLE we_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
  END IF;
END $$;

CREATE SCHEMA IF NOT EXISTS platform;
CREATE SCHEMA IF NOT EXISTS iam;
CREATE SCHEMA IF NOT EXISTS kernel;
CREATE SCHEMA IF NOT EXISTS event_store;
CREATE SCHEMA IF NOT EXISTS projection;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS evidence;
CREATE SCHEMA IF NOT EXISTS governance;
CREATE SCHEMA IF NOT EXISTS ai;
CREATE SCHEMA IF NOT EXISTS intelligence;
CREATE SCHEMA IF NOT EXISTS workflow;
CREATE SCHEMA IF NOT EXISTS obligation;
CREATE SCHEMA IF NOT EXISTS knowledge;
CREATE SCHEMA IF NOT EXISTS legacy;
CREATE SCHEMA IF NOT EXISTS communication;
CREATE SCHEMA IF NOT EXISTS api;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA platform, iam, kernel, event_store, projection, audit, evidence, governance, ai,
  intelligence, workflow, obligation, knowledge, legacy, communication, api TO we_app;
GRANT USAGE ON SCHEMA platform, event_store, projection TO we_worker;

-- Contexto de tenant (definido por transação com set_config(..., true) a partir de claims OIDC validadas).
CREATE OR REPLACE FUNCTION platform.current_tenant() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('we.tenant_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION platform.platform_scope() RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT coalesce(current_setting('we.platform_scope', true), '') = 'on'
$$;

-- Trigger de imutabilidade: bloqueia UPDATE/DELETE em tabelas históricas.
CREATE OR REPLACE FUNCTION platform.forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'WE-APPEND-ONLY: % em %.% não é permitido', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME
    USING ERRCODE = 'insufficient_privilege';
END $$;

-- Ativa RLS deny-by-default com política de isolamento por tenant.
CREATE OR REPLACE FUNCTION platform.enable_tenant_rls(tbl regclass) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', tbl);
  EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', tbl);
  EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %s', tbl);
  EXECUTE format(
    'CREATE POLICY tenant_isolation ON %s USING (tenant_id = platform.current_tenant()) '
    'WITH CHECK (tenant_id = platform.current_tenant())', tbl);
END $$;

CREATE OR REPLACE FUNCTION platform.make_append_only(tbl regclass) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  EXECUTE format('DROP TRIGGER IF EXISTS append_only ON %s', tbl);
  EXECUTE format('CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON %s '
                 'FOR EACH ROW EXECUTE FUNCTION platform.forbid_mutation()', tbl);
  EXECUTE format('DROP TRIGGER IF EXISTS append_only_truncate ON %s', tbl);
  EXECUTE format('CREATE TRIGGER append_only_truncate BEFORE TRUNCATE ON %s '
                 'FOR EACH STATEMENT EXECUTE FUNCTION platform.forbid_mutation()', tbl);
END $$;

-- ───────────────────────── Platform & Tenancy ─────────────────────────
CREATE TABLE platform.tenants (
  tenant_id     uuid PRIMARY KEY,
  slug          text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{2,62}$'),
  display_name  text NOT NULL,
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','closed')),
  data_region   text NOT NULL DEFAULT 'NAO_INDICADO',
  is_synthetic  boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE platform.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE platform.tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_self ON platform.tenants FOR SELECT
  USING (tenant_id = platform.current_tenant() OR platform.platform_scope());
CREATE POLICY tenant_create ON platform.tenants FOR INSERT WITH CHECK (platform.platform_scope());
GRANT SELECT, INSERT ON platform.tenants TO we_app;

CREATE TABLE platform.organizations (
  organization_id uuid PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  name            text NOT NULL,
  legal_form      text,
  country_code    char(2) NOT NULL DEFAULT 'PT',
  tax_identifier  text,           -- texto, nunca numérico; nos seeds é sempre sintético
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, organization_id)
);
SELECT platform.enable_tenant_rls('platform.organizations');
GRANT SELECT, INSERT, UPDATE ON platform.organizations TO we_app;

-- Cabeças das cadeias de hash (eventos, auditoria) por tenant.
CREATE TABLE platform.chain_heads (
  tenant_id  uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  chain_name text NOT NULL CHECK (chain_name IN ('events','audit')),
  last_seq   bigint NOT NULL DEFAULT 0,
  last_hash  text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, chain_name)
);
SELECT platform.enable_tenant_rls('platform.chain_heads');
GRANT SELECT, INSERT, UPDATE ON platform.chain_heads TO we_app;

-- Catálogo global (aprovado explicitamente como não-tenant): capacidades da plataforma.
CREATE TABLE platform.capabilities (
  capability_code text PRIMARY KEY,
  layer           text NOT NULL,
  description_pt  text NOT NULL,
  side_effects    text NOT NULL DEFAULT 'none' CHECK (side_effects IN ('none','internal','external')),
  enabled         boolean NOT NULL DEFAULT true
);
GRANT SELECT ON platform.capabilities TO we_app;

-- ───────────────────────── Identity & Access ─────────────────────────
CREATE TABLE iam.actors (
  actor_id      uuid PRIMARY KEY,
  tenant_id     uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  idp_subject   text NOT NULL,
  actor_type    text NOT NULL CHECK (actor_type IN ('human','service','ai_agent')),
  display_name  text NOT NULL,
  clearance     text NOT NULL DEFAULT 'internal'
                CHECK (clearance IN ('public','internal','confidential','restricted','secret')),
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, actor_id),
  UNIQUE (tenant_id, idp_subject)
);
SELECT platform.enable_tenant_rls('iam.actors');
GRANT SELECT, INSERT, UPDATE ON iam.actors TO we_app;

CREATE TABLE iam.memberships (
  membership_id   uuid PRIMARY KEY,
  tenant_id       uuid NOT NULL,
  actor_id        uuid NOT NULL,
  organization_id uuid,                       -- NULL = âmbito de todo o tenant
  roles           text[] NOT NULL CHECK (cardinality(roles) > 0),
  valid_from      timestamptz NOT NULL DEFAULT now(),
  valid_to        timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, membership_id),
  FOREIGN KEY (tenant_id, actor_id) REFERENCES iam.actors(tenant_id, actor_id),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES platform.organizations(tenant_id, organization_id)
);
SELECT platform.enable_tenant_rls('iam.memberships');
GRANT SELECT, INSERT, UPDATE ON iam.memberships TO we_app;

-- POLICY (ABAC) versionada; cada versão é imutável.
CREATE TABLE iam.policies (
  policy_id   uuid PRIMARY KEY,
  tenant_id   uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  name        text NOT NULL,
  version     int NOT NULL CHECK (version > 0),
  effect      text NOT NULL CHECK (effect IN ('allow','deny')),
  actions     text[] NOT NULL,
  conditions  jsonb NOT NULL DEFAULT '{}'::jsonb,
  description text,
  status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired')),
  created_by  uuid NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, policy_id),
  UNIQUE (tenant_id, name, version),
  FOREIGN KEY (tenant_id, created_by) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('iam.policies');
SELECT platform.make_append_only('iam.policies');
GRANT SELECT, INSERT ON iam.policies TO we_app;

-- ───────────────────────── Cognitive Kernel ─────────────────────────
-- CONTEXT_FRAME: snapshot versionado e imutável. Alterar contexto = nova versão.
CREATE TABLE kernel.context_frames (
  context_frame_id uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  organization_id  uuid,
  frame_key        text NOT NULL,
  version          int NOT NULL CHECK (version > 0),
  purpose          text NOT NULL,
  jurisdiction     text NOT NULL DEFAULT 'PT',
  valid_from       timestamptz,
  valid_to         timestamptz,
  snapshot         jsonb NOT NULL,
  snapshot_hash    text NOT NULL,
  supersedes_id    uuid,
  created_by       uuid NOT NULL,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, context_frame_id),
  UNIQUE (tenant_id, frame_key, version),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES platform.organizations(tenant_id, organization_id),
  FOREIGN KEY (tenant_id, supersedes_id) REFERENCES kernel.context_frames(tenant_id, context_frame_id),
  FOREIGN KEY (tenant_id, created_by) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('kernel.context_frames');
SELECT platform.make_append_only('kernel.context_frames');
GRANT SELECT, INSERT ON kernel.context_frames TO we_app;

CREATE TABLE kernel.entities (
  entity_id       uuid PRIMARY KEY,
  tenant_id       uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  organization_id uuid,
  entity_type     text NOT NULL CHECK (entity_type ~ '^[a-z][a-z0-9_]{1,62}$'),
  display_name    text NOT NULL,
  classification  text NOT NULL DEFAULT 'internal'
                  CHECK (classification IN ('public','internal','confidential','restricted','secret')),
  attributes      jsonb NOT NULL DEFAULT '{}'::jsonb,
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  version         int NOT NULL DEFAULT 1 CHECK (version > 0),
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, entity_id),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES platform.organizations(tenant_id, organization_id)
);
SELECT platform.enable_tenant_rls('kernel.entities');
GRANT SELECT, INSERT, UPDATE ON kernel.entities TO we_app;
CREATE INDEX ON kernel.entities (tenant_id, entity_type);

-- Identificadores (NIF, NISS, IBAN, ...) sempre como texto e classificados como restricted.
CREATE TABLE kernel.entity_identifiers (
  identifier_id  uuid PRIMARY KEY,
  tenant_id      uuid NOT NULL,
  entity_id      uuid NOT NULL,
  scheme         text NOT NULL CHECK (scheme ~ '^[A-Z][A-Z0-9_]{1,31}$'),
  value_text     text NOT NULL,
  country_code   char(2) NOT NULL DEFAULT 'PT',
  classification text NOT NULL DEFAULT 'restricted',
  is_synthetic   boolean NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, scheme, value_text),
  FOREIGN KEY (tenant_id, entity_id) REFERENCES kernel.entities(tenant_id, entity_id)
);
SELECT platform.enable_tenant_rls('kernel.entity_identifiers');
GRANT SELECT, INSERT ON kernel.entity_identifiers TO we_app;

-- ROLE: papel que uma entidade desempenha num âmbito (não confundir com papéis RBAC de iam.memberships).
CREATE TABLE kernel.entity_roles (
  role_id         uuid PRIMARY KEY,
  tenant_id       uuid NOT NULL,
  entity_id       uuid NOT NULL,
  role_type       text NOT NULL CHECK (role_type ~ '^[a-z][a-z0-9_]{1,62}$'),
  organization_id uuid,
  valid_from      timestamptz NOT NULL DEFAULT now(),
  valid_to        timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, role_id),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  FOREIGN KEY (tenant_id, entity_id) REFERENCES kernel.entities(tenant_id, entity_id),
  FOREIGN KEY (tenant_id, organization_id) REFERENCES platform.organizations(tenant_id, organization_id)
);
SELECT platform.enable_tenant_rls('kernel.entity_roles');
GRANT SELECT, INSERT, UPDATE ON kernel.entity_roles TO we_app;

CREATE TABLE kernel.relations (
  relation_id      uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL,
  source_entity_id uuid NOT NULL,
  target_entity_id uuid NOT NULL,
  relation_type    text NOT NULL CHECK (relation_type ~ '^[a-z][a-z0-9_]{1,62}$'),
  attributes       jsonb NOT NULL DEFAULT '{}'::jsonb,
  valid_from       timestamptz NOT NULL DEFAULT now(),
  valid_to         timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, relation_id),
  CHECK (source_entity_id <> target_entity_id),
  CHECK (valid_to IS NULL OR valid_to > valid_from),
  FOREIGN KEY (tenant_id, source_entity_id) REFERENCES kernel.entities(tenant_id, entity_id),
  FOREIGN KEY (tenant_id, target_entity_id) REFERENCES kernel.entities(tenant_id, entity_id)
);
SELECT platform.enable_tenant_rls('kernel.relations');
GRANT SELECT, INSERT, UPDATE ON kernel.relations TO we_app;
CREATE INDEX ON kernel.relations (tenant_id, source_entity_id);
CREATE INDEX ON kernel.relations (tenant_id, target_entity_id);
