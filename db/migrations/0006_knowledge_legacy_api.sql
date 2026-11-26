-- WE · 0006 · Knowledge Repository (pgvector), Legacy Integration (staging/ACL) e idempotência HTTP.

CREATE TABLE knowledge.sources (
  source_id        uuid PRIMARY KEY,
  tenant_id        uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  name             text NOT NULL,
  kind             text NOT NULL CHECK (kind IN ('json_deposit','json_schema','xlsx','docx','sql','markdown','txt','zip','other')),
  logical_path     text NOT NULL,
  sha256           text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes       bigint NOT NULL,
  classification   text NOT NULL DEFAULT 'confidential',
  authority_rank   int NOT NULL CHECK (authority_rank BETWEEN 1 AND 8),
  evidence_status  text NOT NULL CHECK (evidence_status IN ('FACTO_CONFIRMADO','DECISAO_APROVADA','INFERIDO_A_VALIDAR',
                                      'PROPOSTA_TECNICA','DESATUALIZADO_OU_CONFLITUANTE','NAO_INDICADO')),
  jurisdiction     text,
  effective_from   date,
  effective_to     date,
  human_validated  boolean NOT NULL DEFAULT false,
  provenance       jsonb NOT NULL DEFAULT '{}'::jsonb,
  registered_by    uuid NOT NULL,
  registered_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, source_id),
  UNIQUE (tenant_id, sha256, logical_path),
  FOREIGN KEY (tenant_id, registered_by) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('knowledge.sources');
SELECT platform.make_append_only('knowledge.sources');
GRANT SELECT, INSERT ON knowledge.sources TO we_app;

CREATE TABLE knowledge.nodes (
  node_id        uuid PRIMARY KEY,
  tenant_id      uuid NOT NULL,
  source_id      uuid NOT NULL,
  node_type      text NOT NULL,
  node_key       text NOT NULL,
  title          text NOT NULL,
  body           jsonb NOT NULL,
  provenance     jsonb NOT NULL,             -- ficheiro, JSON pointer / folha / secção, hash
  version        int NOT NULL DEFAULT 1,
  classification text NOT NULL DEFAULT 'internal',
  status         text NOT NULL DEFAULT 'imported_unvalidated'
                 CHECK (status IN ('imported_unvalidated','validated','rejected','superseded')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, node_id),
  UNIQUE (tenant_id, source_id, node_key, version),
  FOREIGN KEY (tenant_id, source_id) REFERENCES knowledge.sources(tenant_id, source_id)
);
SELECT platform.enable_tenant_rls('knowledge.nodes');
GRANT SELECT, INSERT, UPDATE (status) ON knowledge.nodes TO we_app;

CREATE TABLE knowledge.chunks (
  chunk_id        uuid PRIMARY KEY,
  tenant_id       uuid NOT NULL,
  node_id         uuid NOT NULL,
  ordinal         int NOT NULL,
  text_content    text NOT NULL,
  embedding       vector(256),
  embedding_model text NOT NULL,
  excluded_fields text[] NOT NULL DEFAULT '{}',
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, node_id, ordinal),
  FOREIGN KEY (tenant_id, node_id) REFERENCES knowledge.nodes(tenant_id, node_id)
);
SELECT platform.enable_tenant_rls('knowledge.chunks');
GRANT SELECT, INSERT ON knowledge.chunks TO we_app;
CREATE INDEX chunks_embedding ON knowledge.chunks USING hnsw (embedding vector_cosine_ops);

-- ─────────── Legacy Integration (anti-corruption layer) ───────────
CREATE TABLE legacy.source_systems (
  source_system_code text PRIMARY KEY CHECK (source_system_code ~ '^[A-Z][A-Z0-9_]{1,31}$'),
  name               text NOT NULL,
  technology         text NOT NULL,
  role_in_phase1     text NOT NULL,
  notes_pt           text
);
GRANT SELECT ON legacy.source_systems TO we_app;

CREATE TABLE legacy.import_batches (
  batch_id           uuid PRIMARY KEY,
  tenant_id          uuid NOT NULL REFERENCES platform.tenants(tenant_id),
  source_system_code text NOT NULL REFERENCES legacy.source_systems(source_system_code),
  batch_kind         text NOT NULL CHECK (batch_kind IN ('knowledge_deposit','staging_snapshot','saft_readmodel')),
  status             text NOT NULL DEFAULT 'created'
                     CHECK (status IN ('created','staging','validated','reconciled','failed','rolled_back')),
  parameters         jsonb NOT NULL DEFAULT '{}'::jsonb,
  counts             jsonb NOT NULL DEFAULT '{"read":0,"accepted":0,"transformed":0,"rejected":0,"orphans":0}'::jsonb,
  started_by         uuid NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  finished_at        timestamptz,
  UNIQUE (tenant_id, batch_id),
  FOREIGN KEY (tenant_id, started_by) REFERENCES iam.actors(tenant_id, actor_id)
);
SELECT platform.enable_tenant_rls('legacy.import_batches');
GRANT SELECT, INSERT, UPDATE (status, counts, finished_at) ON legacy.import_batches TO we_app;

CREATE TABLE legacy.raw_snapshots (
  snapshot_id   uuid PRIMARY KEY,
  tenant_id     uuid NOT NULL,
  batch_id      uuid NOT NULL,
  object_name   text NOT NULL,
  sha256        text NOT NULL,
  row_count     bigint,
  storage_key   text,
  captured_at   timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, batch_id) REFERENCES legacy.import_batches(tenant_id, batch_id)
);
SELECT platform.enable_tenant_rls('legacy.raw_snapshots');
SELECT platform.make_append_only('legacy.raw_snapshots');
GRANT SELECT, INSERT ON legacy.raw_snapshots TO we_app;

CREATE TABLE legacy.mapping_rules (
  mapping_rule_id    uuid PRIMARY KEY,
  tenant_id          uuid NOT NULL,
  source_system_code text NOT NULL REFERENCES legacy.source_systems(source_system_code),
  source_object      text NOT NULL,
  source_field       text NOT NULL,
  source_type_confirmed boolean NOT NULL DEFAULT false,   -- tipo confirmado na fonte autoritativa?
  target_object      text NOT NULL,
  target_field       text NOT NULL,
  transform          jsonb NOT NULL DEFAULT '{}'::jsonb,
  data_class         text NOT NULL DEFAULT 'internal' CHECK (data_class IN
                     ('public','internal','confidential','restricted','secret','pii')),
  version            int NOT NULL CHECK (version > 0),
  status             text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','approved','retired')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, source_system_code, source_object, source_field, version),
  -- segredos nunca são mapeados para colunas da WE
  CHECK (data_class <> 'secret' OR target_object = '__DISCARD__')
);
SELECT platform.enable_tenant_rls('legacy.mapping_rules');
SELECT platform.make_append_only('legacy.mapping_rules');
GRANT SELECT, INSERT ON legacy.mapping_rules TO we_app;

CREATE TABLE legacy.legacy_id_map (
  tenant_id          uuid NOT NULL,
  source_system_code text NOT NULL REFERENCES legacy.source_systems(source_system_code),
  source_object      text NOT NULL,
  source_key         text NOT NULL,
  target_type        text NOT NULL,
  target_id          uuid NOT NULL,
  batch_id           uuid NOT NULL,
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, source_system_code, source_object, source_key),
  FOREIGN KEY (tenant_id, batch_id) REFERENCES legacy.import_batches(tenant_id, batch_id)
);
SELECT platform.enable_tenant_rls('legacy.legacy_id_map');
GRANT SELECT, INSERT ON legacy.legacy_id_map TO we_app;

CREATE TABLE legacy.reconciliations (
  reconciliation_id uuid PRIMARY KEY,
  tenant_id     uuid NOT NULL,
  batch_id      uuid NOT NULL,
  check_type    text NOT NULL CHECK (check_type IN ('count','sum','hash','sample','orphans')),
  subject       text NOT NULL,
  expected      text,
  observed      text,
  result        text NOT NULL CHECK (result IN ('pass','fail','not_applicable')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, batch_id) REFERENCES legacy.import_batches(tenant_id, batch_id)
);
SELECT platform.enable_tenant_rls('legacy.reconciliations');
SELECT platform.make_append_only('legacy.reconciliations');
GRANT SELECT, INSERT ON legacy.reconciliations TO we_app;

CREATE TABLE legacy.quarantine (
  quarantine_id uuid PRIMARY KEY,
  tenant_id     uuid NOT NULL,
  batch_id      uuid NOT NULL,
  source_object text NOT NULL,
  source_key    text,
  reason        text NOT NULL,
  details       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, batch_id) REFERENCES legacy.import_batches(tenant_id, batch_id)
);
SELECT platform.enable_tenant_rls('legacy.quarantine');
SELECT platform.make_append_only('legacy.quarantine');
GRANT SELECT, INSERT ON legacy.quarantine TO we_app;

-- Idempotência HTTP: mesma chave + mesmo pedido = mesma resposta; pedido diferente = conflito.
CREATE TABLE api.idempotency_keys (
  tenant_id     uuid NOT NULL,
  idem_key      text NOT NULL CHECK (length(idem_key) BETWEEN 8 AND 200),
  method        text NOT NULL,
  path          text NOT NULL,
  request_hash  text NOT NULL,
  status_code   int NOT NULL,
  response_body jsonb NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, idem_key)
);
SELECT platform.enable_tenant_rls('api.idempotency_keys');
GRANT SELECT, INSERT ON api.idempotency_keys TO we_app;
