"""Canonical Pydantic types.

Frozen by AGENTS.md Section 5 as of Phase 0. Everything downstream imports from
here rather than defining its own shape, so a contract change is a single visible
edit instead of a slow divergence between modules.

Types below the Section 5 block (Chunk, ApprovalToken, TraceRecord...) were added
for layers the contract did not enumerate. They follow the same rule: defined
once, imported everywhere.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.enums import (
    CaseStatus,
    Channel,
    Collection,
    EscalationType,
    Intent,
    MaintenanceCategory,
    Priority,
    RejectionReason,
    ReviewAction,
    RiskTier,
    Role,
)


def utcnow() -> datetime:
    """Timezone-aware now. Naive datetimes in an SLA clock are a silent bug."""
    return datetime.now(timezone.utc)


# ==========================================================================
# Section 5 — canonical contract. Do not redefine.
# ==========================================================================


class AccessScope(BaseModel):
    """Immutable. Passed to every retrieval and connector call.

    Frozen deliberately: a mutable scope is a scope that can be widened halfway
    down a call stack, which is the exact failure design rule #2 exists to
    prevent. Widening must go through `governance.rbac`, which raises.
    """

    actor_id: str
    role: Role
    booking_ids: list[str] = []
    unit_ids: list[str] = []
    project_ids: list[str] = []  # empty + manager/engineer role = all
    work_package_ids: list[str] = []
    model_config = ConfigDict(frozen=True)

    def fingerprint(self) -> str:
        """Stable short identity for cache keys and audit records."""
        parts = [
            self.actor_id,
            self.role.value,
            ",".join(sorted(self.booking_ids)),
            ",".join(sorted(self.unit_ids)),
            ",".join(sorted(self.project_ids)),
            ",".join(sorted(self.work_package_ids)),
        ]
        return "|".join(parts)


class Citation(BaseModel):
    source_name: str
    source_id: str
    section: str | None = None
    effective_date: date | None = None
    is_stale: bool = False


class Classification(BaseModel):
    intent: Intent
    secondary_intent: Intent | None = None
    confidence: float  # 0.0-1.0
    entities: dict[str, str] = {}  # project, tower, unit, customer_id, urgency
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be within 0.0-1.0")
        return v


class AgentFinding(BaseModel):
    """Uniform return type for every specialist agent."""

    agent: str
    status: Literal["ok", "insufficient_data", "conflict", "error"]
    summary: str  # prose, audience-neutral
    structured: dict[str, Any] = {}  # typed fields from connectors
    citations: list[Citation] = []
    confidence: float
    internal_only: bool = False  # true = must not reach a customer

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be within 0.0-1.0")
        return v


class EscalationDecision(BaseModel):
    required: bool
    escalation_type: str | None = None
    owner_team: str | None = None
    sla_hours: int | None = None
    brief: str | None = None
    rationale: str


class ResponseDraft(BaseModel):
    mode: Literal["auto_send", "draft_for_approval", "acknowledgement_only", "refuse"]
    audience: Role
    text: str
    citations: list[Citation] = []
    next_action: str | None = None


# ==========================================================================
# Supporting types (added after Section 5; same one-definition rule applies)
# ==========================================================================


class Chunk(BaseModel):
    """A retrievable unit of corpus text with its full provenance.

    `audience_scope` is carried on the chunk because retrieval filters on it in
    SQL. It is never consulted inside a prompt.
    """

    chunk_id: str
    source_id: str
    source_name: str
    collection: Collection
    section_heading: str | None = None
    chunk_index: int = 0
    content: str
    effective_date: date | None = None
    freshness_days: int = 365
    audience_scope: list[Role] = []
    project_id: str | None = None
    token_estimate: int = 0
    is_stale: bool = False
    score: float = 0.0
    dense_rank: int | None = None
    sparse_rank: int | None = None
    flagged_injection: bool = False

    def to_citation(self) -> Citation:
        return Citation(
            source_name=self.source_name,
            source_id=self.source_id,
            section=self.section_heading,
            effective_date=self.effective_date,
            is_stale=self.is_stale,
        )


class ApprovalToken(BaseModel):
    """Issued only by the review queue when a human approves an action.

    Connectors validate this themselves (AGENTS.md Section 5): the caller cannot
    be trusted to have checked, because the caller is sometimes an agent acting
    on model output.
    """

    token: str
    case_id: str
    approved_by: str
    approved_at: datetime = Field(default_factory=utcnow)
    action_kind: str
    risk_tier: RiskTier


class TraceRecord(BaseModel):
    """One append-only audit row (architecture Section 6.2)."""

    trace_id: str
    case_id: str
    agent: str
    prompt_version: str | None = None
    policy_version: str | None = None
    model: str | None = None
    inputs_hash: str
    retrieved_source_ids: list[str] = []
    output: dict[str, Any] = {}
    confidence: float | None = None
    risk_tier: int | None = None
    decision: str | None = None
    human_actor: str | None = None
    latency_ms: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    timestamp: datetime = Field(default_factory=utcnow)


class LLMUsage(BaseModel):
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    attempts: int = 1
    degraded: bool = False

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMResult(BaseModel):
    text: str
    usage: LLMUsage
    prompt_id: str
    prompt_version: str


class MaintenanceAssessment(BaseModel):
    """Model-classified category + deterministically assigned priority."""

    category: MaintenanceCategory
    priority: Priority
    safety_critical: bool = False
    safety_signal: str | None = None
    assigned_team: str
    sla_hours: int
    warranty_indication: str | None = None
    rationale: str


class SlippageAssessment(BaseModel):
    """Computed in code, never by a model (PRD FR-CON-4)."""

    tower_id: str
    tower_name: str
    milestones_total: int
    milestones_complete: int
    pct_complete: float
    max_slip_days: int
    slipped_milestones: list[str] = []
    flagged: bool = False
    approved_revised_possession: date | None = None


class CaseRecord(BaseModel):
    """Persisted case row, as returned by the API."""

    case_id: str
    actor_id: str
    role: Role
    channel: Channel
    intent: Intent | None = None
    entities: dict[str, str] = {}
    risk_tier: RiskTier | None = None
    status: CaseStatus = CaseStatus.OPEN
    masked_input: str
    response_text: str | None = None
    response_mode: str | None = None
    confidence: float | None = None
    cost_usd: float = 0.0
    cost_tokens: int = 0
    latency_ms: int = 0
    created_at: datetime = Field(default_factory=utcnow)
    first_response_at: datetime | None = None
    closed_at: datetime | None = None


class EscalationRecord(BaseModel):
    esc_id: str
    case_id: str
    escalation_type: EscalationType | str
    owner_team: str
    sla_hours: int
    sla_due: datetime
    brief: str
    status: Literal["open", "acknowledged", "resolved"] = "open"
    assigned_to: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class ReviewItem(BaseModel):
    """A tier-2 draft or tier-3 escalation awaiting a human."""

    review_id: str
    case_id: str
    risk_tier: RiskTier
    audience: Role
    original_request: str
    reasoning_summary: str
    citations: list[Citation] = []
    proposed_response: str
    confidence: float
    sla_due: datetime | None = None
    status: Literal["pending", "approved", "edited", "rejected", "reassigned"] = "pending"
    acted_by: str | None = None
    acted_at: datetime | None = None
    action: ReviewAction | None = None
    rejection_reason: RejectionReason | None = None
    edited_text: str | None = None
    assigned_to: str | None = None
    created_at: datetime = Field(default_factory=utcnow)


class SLAStatus(BaseModel):
    due_at: datetime
    remaining_minutes: int
    breached: bool
    ageing_bucket: Literal["<4h", "4-24h", "1-3d", ">3d"]
    business_hours_only: bool = False
