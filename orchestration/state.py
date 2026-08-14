"""The single object that moves through the orchestration graph.

Agents never mutate this (AGENTS.md Section 6); they return an `AgentFinding` and
the graph merges it. Keeping mutation in one place is what makes the audit trace
a faithful replay rather than an approximation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from core.enums import CaseStatus, Channel, RiskTier, Role
from core.models import (
    AccessScope,
    AgentFinding,
    Classification,
    EscalationDecision,
    ResponseDraft,
    utcnow,
)


class CaseState(BaseModel):
    case_id: str
    channel: Channel
    scope: AccessScope
    raw_input: str
    masked_input: str
    classification: Classification | None = None
    findings: list[AgentFinding] = []
    risk_tier: RiskTier | None = None
    escalation: EscalationDecision | None = None
    response: ResponseDraft | None = None
    trace_ids: list[str] = []
    cost_tokens: int = 0
    error: str | None = None

    # --- fields beyond the Section 5 contract, needed for graph bookkeeping ---
    status: CaseStatus = CaseStatus.OPEN
    cost_usd: float = 0.0
    degraded: bool = False
    degraded_reasons: list[str] = []
    node_log: list[str] = []
    started_at: datetime = Field(default_factory=utcnow)
    thread_of: str | None = None
    metadata: dict[str, Any] = {}

    @property
    def audience(self) -> Role:
        """Whose disclosure rules apply to the final response."""
        return self.scope.role

    def finding(self, agent: str) -> AgentFinding | None:
        for f in self.findings:
            if f.agent == agent:
                return f
        return None

    def external_findings(self) -> list[AgentFinding]:
        """Findings a customer-facing prompt is allowed to see.

        The exclusion happens here, before prompt assembly — architecture
        Section 12 chose separate generation over redact-on-output precisely so
        internal detail is never in the same context window as customer prose.
        """
        return [f for f in self.findings if not f.internal_only]

    def usable_findings(self) -> list[AgentFinding]:
        return [f for f in self.findings if f.status == "ok"]

    def min_confidence(self) -> float:
        scores = [f.confidence for f in self.findings]
        if self.classification:
            scores.append(self.classification.confidence)
        return min(scores) if scores else 0.0

    def note_degradation(self, reason: str) -> None:
        self.degraded = True
        if reason not in self.degraded_reasons:
            self.degraded_reasons.append(reason)

    def elapsed_ms(self) -> int:
        return int((utcnow() - self.started_at).total_seconds() * 1000)
