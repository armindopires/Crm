"""Modelos de contrato HTTP (OpenAPI). Nomes em inglês; descrições em PT-PT."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

Classification = Literal["public", "internal", "confidential", "restricted", "secret"]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")


class Problem(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str = Field(description="Código de erro estável")
    correlation_id: str | None = None
    instance: str | None = None


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded", "fail"]
    checks: dict[str, str] = {}
    version: str


# ── Tenancy ──
class TenantCreate(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,62}$")
    display_name: str = Field(min_length=2, max_length=200)
    organization_name: str = Field(min_length=2, max_length=200)
    admin_subject: str = Field(
        min_length=3, max_length=200, description="Sujeito (sub) do administrador no IdP"
    )
    admin_display_name: str = Field(min_length=2, max_length=200)
    is_synthetic: bool = True


class TenantCreated(Out):
    tenant_id: UUID
    slug: str
    display_name: str
    organization_id: UUID
    admin_actor_id: UUID
    is_synthetic: bool


class TenantOut(Out):
    tenant_id: UUID
    slug: str
    display_name: str
    status: str
    data_region: str
    is_synthetic: bool
    created_at: datetime


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    legal_form: str | None = None
    tax_identifier: str | None = Field(
        default=None,
        pattern=r"^[A-Z0-9-]{3,32}$",
        description="Identificador fiscal como texto (sintético em dev)",
    )


class OrganizationOut(Out):
    organization_id: UUID
    name: str
    legal_form: str | None
    country_code: str
    status: str
    created_at: datetime


class ActorCreate(BaseModel):
    idp_subject: str = Field(min_length=3, max_length=200)
    actor_type: Literal["human", "service", "ai_agent"]
    display_name: str = Field(min_length=2, max_length=200)
    clearance: Classification = "internal"
    roles: list[str] = Field(min_length=1)
    organization_id: UUID | None = None


class ActorOut(Out):
    actor_id: UUID
    actor_type: str
    display_name: str
    clearance: str
    status: str
    roles: list[str]
    organization_id: UUID | None


class PolicyCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,80}$")
    effect: Literal["deny"] = Field(description="Nesta versão só políticas deny (RBAC é a base de allow)")
    actions: list[str] = Field(min_length=1)
    conditions: dict[str, Any] = {}
    description: str | None = None


class PolicyOut(Out):
    policy_id: UUID
    name: str
    version: int
    effect: str
    actions: list[str]
    conditions: dict[str, Any]
    status: str


# ── Kernel ──
class ContextFrameCreate(BaseModel):
    frame_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.:-]{2,120}$")
    purpose: str = Field(min_length=3, max_length=200)
    jurisdiction: str = "PT"
    organization_id: UUID | None = None
    snapshot: dict[str, Any]
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class ContextFrameOut(Out):
    context_frame_id: UUID
    frame_key: str
    version: int
    purpose: str
    jurisdiction: str
    snapshot: dict[str, Any]
    snapshot_hash: str
    supersedes_id: UUID | None
    created_at: datetime


class EntityCreate(BaseModel):
    entity_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    display_name: str = Field(min_length=1, max_length=300)
    classification: Classification = "internal"
    attributes: dict[str, Any] = {}
    organization_id: UUID | None = None
    context_frame_id: UUID | None = None
    source_ref: str | None = Field(default=None, max_length=200)


class EntityPatch(BaseModel):
    display_name: str | None = None
    attributes: dict[str, Any] | None = None
    status: Literal["active", "archived"] | None = None
    classification: Classification | None = None
    context_frame_id: UUID | None = None


class EntityOut(Out):
    entity_id: UUID
    entity_type: str
    display_name: str
    classification: str
    attributes: dict[str, Any]
    organization_id: UUID | None
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    event_id: UUID | None = None


class RoleCreate(BaseModel):
    role_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    organization_id: UUID | None = None


class RoleOut(Out):
    role_id: UUID
    entity_id: UUID
    role_type: str
    organization_id: UUID | None
    valid_from: datetime
    valid_to: datetime | None


class RelationCreate(BaseModel):
    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    attributes: dict[str, Any] = {}


class RelationOut(Out):
    relation_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relation_type: str
    attributes: dict[str, Any]
    valid_from: datetime
    valid_to: datetime | None


# ── Events ──
class EventOut(Out):
    event_id: UUID
    event_type: str
    schema_version: int
    aggregate_type: str
    aggregate_id: UUID
    aggregate_version: int
    chain_seq: int
    context_frame_id: UUID | None
    actor_id: UUID | None
    actor_type: str
    occurred_at: datetime
    recorded_at: datetime
    correlation_id: UUID
    causation_id: UUID | None
    classification: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


class ChainReportOut(BaseModel):
    chain: str
    tenant_id: str
    records: int
    valid: bool
    head_seq: int | None
    problems: list[dict[str, Any]]


class ReplayOut(BaseModel):
    projection: str
    events_replayed: int
    before: dict[str, Any]
    after: dict[str, Any]
    deterministic: bool
    matches_live: bool


class OutboxStatusOut(BaseModel):
    pending: int
    published: int
    dead: int
    projection_lag: dict[str, int]


# ── Evidence ──
class EvidenceOut(Out):
    evidence_id: UUID
    sha256: str
    size_bytes: int
    media_type: str
    filename_safe: str
    classification: str
    retention_class: str
    source: str
    uploaded_by: UUID
    uploaded_at: datetime
    organization_id: UUID | None


class EvidenceLinkCreate(BaseModel):
    target_type: Literal["entity", "event", "workflow_instance", "obligation", "decision", "communication",
                         "signal", "opportunity"]  # fmt: skip
    target_id: UUID
    link_type: str = Field(default="supports", pattern=r"^[a-z_]{3,40}$")


class EvidenceVerifyOut(BaseModel):
    evidence_id: UUID
    sha256_expected: str
    sha256_observed: str | None
    result: Literal["ok", "mismatch", "missing"]
    valid: bool


class CustodyOut(Out):
    action: str
    actor_id: UUID | None
    occurred_at: datetime
    sha256_observed: str | None
    details: dict[str, Any]


# ── Governance ──
class DecisionCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=5000)
    decision_type: str = Field(pattern=r"^[a-z][a-z0-9_]{2,62}$")
    impact_category: Literal[
        "juridico", "fiscal", "financeiro", "laboral", "reputacional", "externo", "interno"
    ]
    context_frame_id: UUID
    evidence_ids: list[UUID] = []
    ai_trace_id: UUID | None = None
    organization_id: UUID | None = None


class DecisionReview(BaseModel):
    verdict: Literal["approved", "rejected"]
    rationale: str = Field(min_length=3, max_length=5000)
    expected_version: int | None = None


class ApprovalOut(Out):
    approval_id: UUID
    approver_id: UUID
    verdict: str
    rationale: str
    created_at: datetime


class DecisionOut(Out):
    decision_id: UUID
    title: str
    description: str | None
    decision_type: str
    impact_category: str
    requires_human_approval: bool
    status: str
    context_frame_id: UUID
    proposed_by: UUID
    proposed_by_type: str
    ai_trace_id: UUID | None
    decided_by: UUID | None
    decided_at: datetime | None
    rationale: str | None
    executed_by: UUID | None
    executed_at: datetime | None
    version: int
    created_at: datetime
    evidence_ids: list[UUID] = []
    approvals: list[ApprovalOut] = []


class AIInvoke(BaseModel):
    capability: Literal["summarize", "classify", "propose_decision"]
    text: str = Field(min_length=1, max_length=20000)
    params: dict[str, Any] = {}


class AIInvokeOut(BaseModel):
    ai_trace_id: UUID
    capability: str
    provider: str
    model: str
    output: dict[str, Any]


# ── Intelligence ──
class SignalCreate(BaseModel):
    signal_type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,62}$")
    source: str = Field(min_length=2, max_length=200)
    strength: str = Field(pattern=r"^(0(\.\d{1,4})?|1(\.0{1,4})?)$", description="Decimal 0..1 em texto")
    description: str = Field(min_length=3, max_length=2000)
    entity_id: UUID | None = None
    context_frame_id: UUID | None = None
    organization_id: UUID | None = None


class SignalOut(Out):
    signal_id: UUID
    signal_type: str
    source: str
    strength: Decimal
    description: str
    entity_id: UUID | None
    context_frame_id: UUID | None
    status: str
    created_at: datetime


class SignalPromote(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    value_estimate: str | None = Field(default=None, pattern=r"^\d{1,16}(\.\d{1,2})?$")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")


class OpportunityOut(Out):
    opportunity_id: UUID
    signal_id: UUID
    title: str
    value_estimate: Decimal | None
    currency: str | None
    status: str
    owner_actor_id: UUID
    created_at: datetime


# ── Audit ──
class AuditOut(Out):
    audit_id: UUID
    chain_seq: int
    occurred_at: datetime
    actor_id: UUID | None
    actor_type: str
    actor_ref: str
    action: str
    resource_type: str
    resource_id: str | None
    outcome: str
    reason: str | None
    policy_refs: list[str]
    correlation_id: UUID
    record_hash: str


# ── Knowledge / Legacy ──
class SourceSystemOut(Out):
    source_system_code: str
    name: str
    technology: str
    role_in_phase1: str
    notes_pt: str | None


class SourceOut(Out):
    source_id: UUID
    name: str
    kind: str
    logical_path: str
    sha256: str
    size_bytes: int
    classification: str
    authority_rank: int
    evidence_status: str
    human_validated: bool
    registered_at: datetime


class ImportBatchCreate(BaseModel):
    source_system_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,31}$")
    batch_kind: Literal["staging_snapshot", "saft_readmodel"]
    parameters: dict[str, Any] = {}


class ImportBatchOut(Out):
    batch_id: UUID
    source_system_code: str
    batch_kind: str
    status: str
    counts: dict[str, int]
    parameters: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None
    reconciliations: list[dict[str, Any]] = []


class SystemStatusOut(BaseModel):
    tenant: TenantOut
    counts: dict[str, int]
    outbox: OutboxStatusOut
    chains: dict[str, bool]
