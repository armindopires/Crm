-- WE · 0008 · Métricas operacionais agregadas (sem conteúdo de tenants) para o worker.
CREATE OR REPLACE FUNCTION governance.pending_decisions_count() RETURNS bigint
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, governance AS $$
  SELECT count(*) FROM governance.decisions WHERE status IN ('proposed','under_review')
$$;
REVOKE ALL ON FUNCTION governance.pending_decisions_count() FROM PUBLIC;
GRANT USAGE ON SCHEMA governance TO we_worker;
GRANT EXECUTE ON FUNCTION governance.pending_decisions_count() TO we_worker;
