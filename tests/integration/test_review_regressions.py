"""Regressões dos achados da revisão independente (2026-11-26)."""

from __future__ import annotations

import hashlib

import pytest
from psycopg import errors

from we_core.ai import gateway
from we_core.errors import Forbidden, ValidationFailed
from we_core.events.store import EventDraft, append
from we_core.governance import service as gov
from we_core.integrity import verify_audit, verify_events
from we_core.kernel import service as kernel
from we_core.platform import service as plat

pytestmark = pytest.mark.integration


def _decision(db, ctx):  # type: ignore[no-untyped-def]
    with db.tenant_tx(ctx.tenant_id) as conn:
        frame = kernel.create_context_frame(conn, ctx, frame_key="rev:1", purpose="teste", snapshot={"a": 1})
        return gov.propose(
            conn,
            ctx,
            title="Decisão",
            description=None,
            decision_type="test_case",
            impact_category="fiscal",
            context_frame_id=frame["context_frame_id"],
            evidence_ids=[],
        )


def test_app_role_cannot_downgrade_human_approval_or_flip_actor_type(db, tenant_factory):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("rev2")
    dec = _decision(db, a)
    with pytest.raises(errors.InsufficientPrivilege), db.tenant_tx(a.tenant_id) as conn:
        conn.execute("UPDATE governance.decisions SET requires_human_approval=false, impact_category='interno' "
                     "WHERE decision_id=%s", (dec["decision_id"],))  # fmt: skip
    with pytest.raises(errors.InsufficientPrivilege), db.tenant_tx(a.tenant_id) as conn:
        conn.execute("UPDATE iam.actors SET actor_type='human'")
    # aprovação sem registo em governance.approvals é recusada pelo trigger
    with db.tenant_tx(a.tenant_id) as conn:
        other = plat.create_actor(conn, a, idp_subject="h@rev.invalid", actor_type="human", display_name="H",
                                  clearance="internal", roles=["approver"], organization_id=None)  # fmt: skip
    with pytest.raises(errors.RaiseException), db.tenant_tx(a.tenant_id) as conn:
        conn.execute("UPDATE governance.decisions SET status='approved', decided_by=%s, decided_at=now() "
                     "WHERE decision_id=%s", (other["actor_id"], dec["decision_id"]))  # fmt: skip


def test_org_scoped_actor_does_not_list_other_org_decisions(db, tenant_factory, settings):  # type: ignore[no-untyped-def]
    from we_core.context import OpContext
    from we_core.identity.principal import resolve_principal

    t, a = tenant_factory("rev4")
    with db.tenant_tx(a.tenant_id) as conn:
        org_b = plat.create_organization(conn, a, name="Org B fictícia", legal_form=None, tax_identifier=None)
        plat.create_actor(conn, a, idp_subject="scoped@rev.invalid", actor_type="human", display_name="S",
                          clearance="confidential", roles=["approver"],
                          organization_id=t["organization_id"])  # fmt: skip
        frame = kernel.create_context_frame(conn, a, frame_key="rev:4", purpose="p", snapshot={},
                                            organization_id=org_b["organization_id"])  # fmt: skip
        gov.propose(conn, a, title="Só org B", description=None, decision_type="test_case", impact_category="fiscal",
                    context_frame_id=frame["context_frame_id"], evidence_ids=[],
                    organization_id=org_b["organization_id"])  # fmt: skip
    scoped = OpContext(
        principal=resolve_principal(
            db, settings, {"sub": "scoped@rev.invalid", settings.oidc_tenant_claim: str(a.tenant_id)}
        )
    )
    with db.tenant_tx(a.tenant_id) as conn:
        assert gov.list_decisions(conn, a, None, 50)  # admin de tenant vê
        assert gov.list_decisions(conn, scoped, None, 50) == []  # âmbito org A não vê org B
        with pytest.raises(Forbidden):
            kernel.get_context_frame(conn, scoped, frame["context_frame_id"])


def test_policy_and_actor_creation_guards(db, tenant_factory):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("rev10")
    with pytest.raises(ValidationFailed), db.tenant_tx(a.tenant_id) as conn:
        plat.create_policy(conn, a, name="mau.tipo", effect="deny", actions=["entity:read"],
                           conditions={"organization_id_in": 5}, description=None)  # fmt: skip
    with pytest.raises(Forbidden), db.tenant_tx(a.tenant_id) as conn:  # admin tem 'restricted'
        plat.create_actor(conn, a, idp_subject="x@rev.invalid", actor_type="human", display_name="X",
                          clearance="secret", roles=["auditor"], organization_id=None)  # fmt: skip


def test_floats_rejected_and_ai_input_hash_is_keyed(db, tenant_factory):  # type: ignore[no-untyped-def]
    from we_core.common import uuid7

    _, a = tenant_factory("rev5")
    with pytest.raises(ValidationFailed), db.tenant_tx(a.tenant_id) as conn:
        append(conn, a, EventDraft(event_type="intelligence.signal_detected", aggregate_type="signal",
                                   aggregate_id=uuid7(), payload={"signal_type": "x_t", "source": "s",
                                                                  "strength": 0.5, "entity_id": None}))  # fmt: skip
    with db.tenant_tx(a.tenant_id) as conn:
        out = gateway.invoke(
            conn, a, gateway.LocalHeuristicProvider(), capability="classify", text="999999990"
        )
        row = conn.execute("SELECT input_hash FROM ai.ai_traces WHERE ai_trace_id=%s",
                           (out["ai_trace_id"],)).fetchone()  # fmt: skip
    assert row["input_hash"] != hashlib.sha256(b"999999990").hexdigest()


def test_chain_verification_has_no_false_truncation_under_concurrent_append(db, tenant_factory):  # type: ignore[no-untyped-def]
    _, a = tenant_factory("rev7")
    with db.tenant_tx(a.tenant_id) as conn:
        kernel.create_context_frame(conn, a, frame_key="rev:7", purpose="p", snapshot={})
    with db.tenant_tx(a.tenant_id) as verifier:
        first = verify_events(verifier, a.tenant_id)
        with db.tenant_tx(a.tenant_id) as writer:  # escrita concorrente comprometida a meio
            kernel.create_context_frame(writer, a, frame_key="rev:7b", purpose="p", snapshot={})
        second, audit_rep = verify_events(verifier, a.tenant_id), verify_audit(verifier, a.tenant_id)
    assert first.valid and second.valid and audit_rep.valid
