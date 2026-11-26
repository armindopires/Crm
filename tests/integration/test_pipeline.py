"""Outbox (retry/DLQ), consumidores idempotentes, replay, evidência adulterada e importador de conhecimento."""

from __future__ import annotations

import asyncio
import json

import psycopg
import pytest

from we_core.db import Database
from we_core.events import outbox, projections
from we_core.events.bus import InMemoryBus
from we_core.evidence import service as evidence
from we_core.evidence.storage import MemoryStorage
from we_core.kernel import service as kernel

pytestmark = pytest.mark.integration


@pytest.fixture
def worker_db(settings):  # type: ignore[no-untyped-def]
    d = Database(settings.dsn("worker"), 1, 2)
    d.open()
    yield d
    d.close()


def test_outbox_retries_then_dead_letters_then_requeue(db, worker_db, admin_dsn, tenant_factory):  # type: ignore[no-untyped-def]
    # segura o lease de publicador para que o worker real (se ativo) não publique durante o teste
    lease = psycopg.connect(admin_dsn, autocommit=True)
    lease.execute("SELECT pg_advisory_lock(%s)", (outbox.PUBLISHER_LEASE,))
    _, a = tenant_factory("ob")
    with db.tenant_tx(a.tenant_id) as conn:
        kernel.create_entity(conn, a, entity_type="x_type", display_name="x", classification="internal",
                             attributes={}, organization_id=None, context_frame_id=None)  # fmt: skip
    bus = InMemoryBus()
    bus.fail_next = 1
    stats = asyncio.run(outbox.publish_batch(worker_db, bus, tenant_id=a.tenant_id, use_lease=False))
    assert stats.retried == 1 and stats.published == 0
    with psycopg.connect(admin_dsn, autocommit=True) as su:
        su.execute("UPDATE event_store.outbox SET next_attempt_at = now(), attempts = %s WHERE tenant_id = %s "
                   "AND status='pending'", (outbox.MAX_ATTEMPTS - 1, a.tenant_id))  # fmt: skip
    bus.fail_next = 1
    stats = asyncio.run(outbox.publish_batch(worker_db, bus, tenant_id=a.tenant_id, use_lease=False))
    assert stats.dead == 1
    with psycopg.connect(admin_dsn, autocommit=True) as su:
        su.execute("UPDATE event_store.outbox SET status='pending', attempts=0, next_attempt_at=now() "
                   "WHERE tenant_id=%s AND status='dead'", (a.tenant_id,))  # fmt: skip
    stats = asyncio.run(outbox.publish_batch(worker_db, bus, tenant_id=a.tenant_id, use_lease=False))
    assert stats.published >= 1 and len(bus.messages) >= 1
    lease.close()
    # republicar o mesmo event_id não duplica (dedupe por Nats-Msg-Id / msg_id)
    subject, env = bus.messages[0]
    assert asyncio.run(bus.publish(subject, env, env["event_id"])) is False


def test_consumer_is_idempotent_and_replay_is_deterministic(db, tenant_factory):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("proj")
    with db.tenant_tx(a.tenant_id) as conn:
        e = kernel.create_entity(conn, a, entity_type="x_type", display_name="x", classification="internal",
                                 attributes={}, organization_id=None, context_frame_id=None)  # fmt: skip
        kernel.update_entity(conn, a, e["entity_id"], expected_version=1, changes={"status": "archived"},
                             context_frame_id=None)  # fmt: skip
        events = conn.execute("SELECT * FROM event_store.events WHERE aggregate_id=%s ORDER BY chain_seq",
                              (e["entity_id"],)).fetchall()  # fmt: skip
        projections.replay(conn, a.tenant_id)  # começa de estado limpo
        for ev in events:  # entrega at-least-once: o mesmo evento chega duas vezes
            assert projections.apply(conn, ev) is False
        row = conn.execute("SELECT event_count FROM projection.entity_summary WHERE entity_id=%s",
                           (e["entity_id"],)).fetchone()  # fmt: skip
        assert row["event_count"] == 2
        out = projections.replay(conn, a.tenant_id)
        assert out["deterministic"] and out["matches_live"]


def test_evidence_tampering_is_detected(db, tenant_factory, settings):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("evd")
    store = MemoryStorage()
    with db.tenant_tx(a.tenant_id) as conn:
        ev = evidence.register(conn, a, store, data=b"conteudo ficticio\n", filename="x.txt", media_type="text/plain",
                               classification="internal", source="teste", max_bytes=1024)  # fmt: skip
        assert evidence.verify(conn, a, store, ev["evidence_id"])["valid"]
    store.objects[ev["storage_key"]] = b"conteudo adulterado\n"
    with db.tenant_tx(a.tenant_id) as conn:
        res = evidence.verify(conn, a, store, ev["evidence_id"])
        assert res["result"] == "mismatch" and not res["valid"]
        acts = [c["action"] for c in evidence.custody(conn, a, ev["evidence_id"])]
    assert acts == ["uploaded", "verified", "verification_failed"]


def test_restricted_evidence_policy_requires_audit_purpose(db, tenant_factory):  # type: ignore[no-untyped-def]
    from we_core.errors import Forbidden
    from we_core.platform import service as plat

    _, a = tenant_factory("pol")
    store = MemoryStorage()
    with db.tenant_tx(a.tenant_id) as conn:
        plat.create_policy(conn, a, name="evidence.restricted.audit-only", effect="deny", actions=["evidence:read"],
                           conditions={"classification_in": ["restricted"], "purpose_not_in": ["audit"]},
                           description=None)  # fmt: skip
        ev = evidence.register(
            conn,
            a,
            store,
            data=b"%PDF-1.4 sintetico",
            filename="r.pdf",
            media_type="application/pdf",
            classification="restricted",
            source="t",
            max_bytes=999,
        )
    with pytest.raises(Forbidden), db.tenant_tx(a.tenant_id) as conn:
        evidence.get(conn, a, ev["evidence_id"])
    a.purpose = "audit"
    with db.tenant_tx(a.tenant_id) as conn:
        assert evidence.get(conn, a, ev["evidence_id"])["classification"] == "restricted"


def test_knowledge_import_validates_schema_and_excludes_secrets(db, tenant_factory, tmp_path):  # type: ignore[no-untyped-def]
    from we_core.knowledge.importer import import_deposit, search

    _, a = tenant_factory("kn")
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["tabelas"],
        "properties": {"tabelas": {"type": "array", "items": {"type": "object", "required": ["nome"]}}},
    }
    good = {"tabelas": [{"id": "T1", "nome": "CLIENTES_FICTICIOS", "pk": "ID", "senha_bd": "nunca-migrar"},
                        {"id": "T2", "nome": "FATURAS_FICTICIAS", "nif": "999999990"}]}  # fmt: skip
    with db.tenant_tx(a.tenant_id) as conn:
        out = import_deposit(conn, a, deposit_bytes=json.dumps(good).encode(), schema_bytes=json.dumps(schema).encode(),
                             logical_path="sintetico/crmcontab.json", schema_path="sintetico/crmcontab.schema.json",
                             source_system_code="CRMCONTAB")  # fmt: skip
        assert out["status"] == "reconciled" and out["nodes_created"] == 2 and out["fields_excluded"] == 2
        bodies = [r["body"] for r in conn.execute("SELECT body FROM knowledge.nodes WHERE source_id=%s",
                                                  (out["source_id"],))]  # fmt: skip
        assert all("senha_bd" not in b for b in bodies)
        texts = " ".join(r["text_content"] for r in conn.execute("SELECT text_content FROM knowledge.chunks"))
        assert "nunca-migrar" not in texts and "999999990" not in texts
        assert search(conn, a, "clientes", 1)[0]["title"] == "CLIENTES_FICTICIOS"
        bad = import_deposit(conn, a, deposit_bytes=b'{"tabelas": [{"sem_nome": 1}]}',
                             schema_bytes=json.dumps(schema).encode(), logical_path="sintetico/invalido.json",
                             schema_path="s.json", source_system_code="CRMCONTAB")  # fmt: skip
        assert bad["status"] == "failed"
        q = conn.execute(
            "SELECT count(*) AS n FROM legacy.quarantine WHERE batch_id=%s", (bad["batch_id"],)
        ).fetchone()
        assert q["n"] >= 1
        assert conn.execute("SELECT count(*) AS n FROM knowledge.sources WHERE logical_path='sintetico/invalido.json'"
                            ).fetchone()["n"] == 0  # fmt: skip
