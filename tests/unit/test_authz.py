from uuid import uuid4

from we_core.context import Principal
from we_core.identity.authz import Resource, evaluate


def P(**kw):
    base = {
        "subject": "s",
        "actor_id": uuid4(),
        "tenant_id": uuid4(),
        "actor_type": "human",
        "roles": frozenset({"operator"}),
        "clearance": "confidential",
    }
    base.update(kw)
    return Principal(**base)


def test_deny_by_default_without_role():
    d = evaluate(None, P(roles=frozenset()), "entity:read", Resource("entity"))
    assert not d.allowed


def test_operator_cannot_approve_decisions():
    assert not evaluate(None, P(), "decision:approve", Resource("decision")).allowed


def test_ai_agent_never_approves_even_with_role():
    p = P(actor_type="ai_agent", roles=frozenset({"approver"}))
    d = evaluate(None, p, "decision:approve", Resource("decision"))
    assert not d.allowed and "hitl:human_only" in d.policy_refs


def test_clearance_blocks_higher_classification():
    d = evaluate(
        None, P(clearance="internal"), "entity:read", Resource("entity", classification="restricted")
    )
    assert not d.allowed and "abac:clearance" in d.policy_refs


def test_org_scope_blocks_other_organization():
    org_a, org_b = uuid4(), uuid4()
    p = P(org_scope=frozenset({org_a}))
    assert evaluate(None, p, "entity:read", Resource("entity", organization_id=org_a)).allowed
    assert not evaluate(None, p, "entity:read", Resource("entity", organization_id=org_b)).allowed


def test_platform_admin_can_only_create_tenants():
    p = Principal(
        subject="p",
        actor_id=None,
        tenant_id=None,
        actor_type="human",
        platform_roles=frozenset({"platform_admin"}),
    )
    assert evaluate(None, p, "tenant:create", Resource("tenant")).allowed
    assert not evaluate(None, p, "entity:read", Resource("entity")).allowed
