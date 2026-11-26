"""Testes adversariais: isolamento multi-tenant (RLS), append-only, adulteração, HITL na base de dados."""

from __future__ import annotations

import psycopg
import pytest
from psycopg import errors

from we_core.audit import log as audit
from we_core.common import uuid7
from we_core.events.store import EventDraft, append
from we_core.integrity import verify_audit, verify_events
from we_core.kernel import service as kernel

pytestmark = pytest.mark.integration

TENANT_TABLES = [
    "platform.organizations", "iam.actors", "iam.memberships", "iam.policies", "kernel.entities",
    "kernel.context_frames", "kernel.relations", "event_store.events", "event_store.outbox", "audit.audit_log",
    "evidence.evidence", "evidence.custody_events", "governance.decisions", "ai.ai_traces", "intelligence.signals",
    "knowledge.sources", "knowledge.nodes", "legacy.import_batches", "api.idempotency_keys",
]  # fmt: skip


def _entity(db, ctx, name="Entidade fictícia"):  # type: ignore[no-untyped-def]
    with db.tenant_tx(ctx.tenant_id) as conn:
        return kernel.create_entity(conn, ctx, entity_type="client_company", display_name=name,
                                    classification="internal", attributes={"x": 1}, organization_id=None,
                                    context_frame_id=None)  # fmt: skip


def test_rls_denies_everything_without_tenant_context(db, tenant_factory):  # type: ignore[no-untyped-def]
    _, ctx = tenant_factory("rls")
    _entity(db, ctx)
    with db.tenant_tx(None) as conn:
        for t in TENANT_TABLES:
            assert conn.execute(f"SELECT count(*) AS n FROM {t}").fetchone()["n"] == 0, t
        assert conn.execute("SELECT count(*) AS n FROM platform.tenants").fetchone()["n"] == 0


def test_tenant_cannot_read_enumerate_or_search_another(db, tenant_factory):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("ta")
    _, b = tenant_factory("tb")
    ent = _entity(db, a, "Segredo comercial fictício")
    with db.tenant_tx(b.tenant_id) as conn:
        assert (
            conn.execute("SELECT * FROM kernel.entities WHERE entity_id = %s", (ent["entity_id"],)).fetchone()
            is None
        )
        assert conn.execute("SELECT count(*) AS n FROM kernel.entities WHERE display_name ILIKE '%%Segredo%%'"
                            ).fetchone()["n"] == 0  # fmt: skip
        assert conn.execute("SELECT count(*) AS n FROM event_store.events WHERE aggregate_id = %s",
                            (ent["entity_id"],)).fetchone()["n"] == 0  # fmt: skip
        # inferência por unicidade: o mesmo idempotency_key noutro tenant não colide
        assert conn.execute("SELECT count(*) AS n FROM platform.tenants").fetchone()["n"] == 1


def test_tenant_cannot_write_into_another(db, tenant_factory):  # type: ignore[no-untyped-def]
    ta, a = tenant_factory("wa")
    _, b = tenant_factory("wb")
    ent = _entity(db, a)
    # 1) inserir linha com tenant_id alheio → WITH CHECK da RLS
    with pytest.raises(errors.InsufficientPrivilege), db.tenant_tx(b.tenant_id) as conn:
        conn.execute("INSERT INTO kernel.entities (entity_id, tenant_id, entity_type, display_name) "
                     "VALUES (%s, %s, 'x_type', 'intrusa')", (uuid7(), ta["tenant_id"]))  # fmt: skip
    # 2) referenciar entidade de outro tenant → FK composta (tenant_id, id) falha
    with pytest.raises(errors.ForeignKeyViolation), db.tenant_tx(b.tenant_id) as conn:
        own = conn.execute("INSERT INTO kernel.entities (entity_id, tenant_id, entity_type, display_name) "
                           "VALUES (%s, %s, 'x_type', 'propria') RETURNING entity_id",
                           (uuid7(), b.tenant_id)).fetchone()["entity_id"]  # fmt: skip
        conn.execute(
            "INSERT INTO kernel.relations (relation_id, tenant_id, source_entity_id, target_entity_id, "
            "relation_type) VALUES (%s,%s,%s,%s,'links_to')",
            (uuid7(), b.tenant_id, own, ent["entity_id"]),
        )
    # 3) UPDATE/DELETE de linhas alheias afeta zero linhas
    with db.tenant_tx(b.tenant_id) as conn:
        assert conn.execute("UPDATE kernel.entities SET display_name='x' WHERE entity_id=%s",
                            (ent["entity_id"],)).rowcount == 0  # fmt: skip


def test_tenant_context_does_not_leak_through_pool(db, tenant_factory):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("pool")
    with db.tenant_tx(a.tenant_id) as conn:
        assert conn.execute("SELECT current_setting('we.tenant_id', true) AS t").fetchone()["t"] == str(
            a.tenant_id
        )
    for _ in range(db.pool.max_size + 1):
        with db.pool.connection() as conn:
            assert (
                conn.execute("SELECT coalesce(current_setting('we.tenant_id', true),'') AS t").fetchone()["t"]
                == ""
            )


@pytest.mark.parametrize("table", ["event_store.events", "audit.audit_log", "evidence.evidence",
                                   "kernel.context_frames", "governance.approvals"])  # fmt: skip
def test_app_role_cannot_update_delete_or_truncate_history(db, tenant_factory, table):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("ao")
    _entity(db, a)
    for stmt in (f"UPDATE {table} SET tenant_id = tenant_id", f"DELETE FROM {table}", f"TRUNCATE {table}"):
        with pytest.raises(errors.InsufficientPrivilege), db.tenant_tx(a.tenant_id) as conn:
            conn.execute(stmt)


def test_event_idempotency_and_optimistic_concurrency(db, tenant_factory):  # type: ignore[no-untyped-def]
    from we_core.errors import ConcurrencyConflict

    _, a = tenant_factory("idem")
    agg = uuid7()
    draft = EventDraft(event_type="kernel.entity_created", aggregate_type="entity", aggregate_id=agg,
                       expected_version=0, idempotency_key="idem-key-0001",
                       payload={"entity_type": "x_type", "classification": "internal", "organization_id": None,
                                "attribute_keys": []})  # fmt: skip
    with db.tenant_tx(a.tenant_id) as conn:
        first = append(conn, a, draft)
        second = append(conn, a, draft)
        assert not first.duplicate and second.duplicate
        assert second.event["event_id"] == first.event["event_id"]
        n = conn.execute(
            "SELECT count(*) AS n FROM event_store.events WHERE aggregate_id=%s", (agg,)
        ).fetchone()["n"]
        assert n == 1
        with pytest.raises(ConcurrencyConflict):
            append(
                conn,
                a,
                EventDraft(
                    event_type="kernel.entity_updated",
                    aggregate_type="entity",
                    aggregate_id=agg,
                    expected_version=0,
                    payload={
                        "changed_fields": [],
                        "new_version": 2,
                        "status": "active",
                        "classification": "internal",
                    },
                ),
            )


def test_tampering_is_detected_in_event_and_audit_chains(db, admin_dsn, tenant_factory):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("tamper")
    ent = _entity(db, a)
    with db.tenant_tx(a.tenant_id) as conn:
        audit.record(conn, a, action="test.mark", resource_type="test", resource_id=None, outcome="succeeded")
        assert verify_events(conn, a.tenant_id).valid and verify_audit(conn, a.tenant_id).valid
    # atacante com privilégios de DBA, contornando triggers
    with psycopg.connect(admin_dsn, autocommit=True) as su:
        su.execute("SET session_replication_role = replica")
        su.execute("UPDATE event_store.events SET payload = jsonb_set(payload, '{entity_type}', '\"forjado\"') "
                   "WHERE aggregate_id = %s", (ent["entity_id"],))  # fmt: skip
        su.execute("DELETE FROM audit.audit_log WHERE tenant_id = %s AND chain_seq = 1", (a.tenant_id,))
    with db.tenant_tx(a.tenant_id) as conn:
        ev, au = verify_events(conn, a.tenant_id), verify_audit(conn, a.tenant_id)
    assert not ev.valid and any(p["kind"] == "content" for p in ev.problems)
    assert not au.valid and any(p["kind"] in ("gap", "link") for p in au.problems)


def test_decision_guard_in_database_enforces_hitl_and_sod(db, admin_dsn, tenant_factory):  # type: ignore[no-untyped-def]
    from we_core.governance import service as gov
    from we_core.platform import service as plat

    _, a = tenant_factory("gov")
    with db.tenant_tx(a.tenant_id) as conn:
        frame = kernel.create_context_frame(conn, a, frame_key="gov:test", purpose="teste", snapshot={"k": 1})
        bot = plat.create_actor(conn, a, idp_subject="bot@gov.invalid", actor_type="ai_agent", display_name="Bot",
                                clearance="internal", roles=["ai_agent"], organization_id=None)  # fmt: skip
        dec = gov.propose(
            conn,
            a,
            title="Decisão teste",
            description=None,
            decision_type="test_case",
            impact_category="fiscal",
            context_frame_id=frame["context_frame_id"],
            evidence_ids=[],
        )
    did = dec["decision_id"]
    # mesmo contornando a API: proponente não aprova; IA não aprova; proposto não salta para executado
    for stmt, params in (
        ("UPDATE governance.decisions SET status='approved', decided_by=proposed_by, decided_at=now() "
         "WHERE decision_id=%s", (did,)),
        ("UPDATE governance.decisions SET status='approved', decided_by=%s, decided_at=now() WHERE decision_id=%s",
         (bot["actor_id"], did)),
        ("UPDATE governance.decisions SET status='executed', executed_by=proposed_by, executed_at=now() "
         "WHERE decision_id=%s", (did,)),
    ):  # fmt: skip
        with pytest.raises(errors.RaiseException), db.tenant_tx(a.tenant_id) as conn:
            conn.execute(stmt, params)
    with db.tenant_tx(a.tenant_id) as conn:
        assert conn.execute("SELECT status FROM governance.decisions WHERE decision_id=%s",
                            (did,)).fetchone()["status"] == "proposed"  # fmt: skip


def test_context_frames_are_versioned_not_mutated(db, tenant_factory):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("ctx")
    with db.tenant_tx(a.tenant_id) as conn:
        v1 = kernel.create_context_frame(conn, a, frame_key="c:1", purpose="p", snapshot={"a": 1})
        v2 = kernel.create_context_frame(conn, a, frame_key="c:1", purpose="p", snapshot={"a": 2})
    assert (v1["version"], v2["version"]) == (1, 2) and v2["supersedes_id"] == v1["context_frame_id"]
    with pytest.raises(errors.InsufficientPrivilege), db.tenant_tx(a.tenant_id) as conn:
        conn.execute("UPDATE kernel.context_frames SET snapshot='{}' WHERE context_frame_id=%s",
                     (v1["context_frame_id"],))  # fmt: skip


def test_secrets_are_refused_in_entity_attributes(db, tenant_factory):  # type: ignore[no-untyped-def]
    from we_core.errors import ValidationFailed

    _, a = tenant_factory("sec")
    with pytest.raises(ValidationFailed), db.tenant_tx(a.tenant_id) as conn:
        kernel.create_entity(conn, a, entity_type="x_type", display_name="x", classification="internal",
                             attributes={"ligacao": {"db_password": "x"}}, organization_id=None,
                             context_frame_id=None)  # fmt: skip
