"""The frozen contract from AGENTS.md Section 5 (build plan P0-T2).

These tests exist to make a contract change loud. Every type here was frozen at
Phase 0, and later tickets were told to report rather than edit — so if one of these
fails, the question is not "fix the test", it is "who changed the contract".
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from core.enums import Channel, Intent, Priority, RiskTier, Role
from core.models import (
    AccessScope,
    AgentFinding,
    Chunk,
    Citation,
    Classification,
    EscalationDecision,
    ResponseDraft,
)
from orchestration.state import CaseState


def test_access_scope_is_immutable() -> None:
    scope = AccessScope(actor_id="CUST-4471", role=Role.CUSTOMER, booking_ids=["BK-9901"])
    with pytest.raises(ValidationError):
        scope.booking_ids = ["BK-9902"]  # type: ignore[misc]
    with pytest.raises(ValidationError):
        scope.role = Role.MANAGER  # type: ignore[misc]


def test_access_scope_fingerprint_is_order_independent() -> None:
    """Cache keys must not change because a list arrived in a different order."""
    first = AccessScope(actor_id="a", role=Role.CUSTOMER, unit_ids=["u1", "u2"])
    second = AccessScope(actor_id="a", role=Role.CUSTOMER, unit_ids=["u2", "u1"])
    assert first.fingerprint() == second.fingerprint()


@pytest.mark.parametrize("value", [-0.1, 1.1, 2.0])
def test_confidence_rejects_out_of_range(value: float) -> None:
    with pytest.raises(ValidationError):
        Classification(intent=Intent.OTHER, confidence=value)
    with pytest.raises(ValidationError):
        AgentFinding(agent="a", status="ok", summary="s", confidence=value)


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_confidence_accepts_the_boundaries(value: float) -> None:
    assert Classification(intent=Intent.OTHER, confidence=value).confidence == value


def test_agent_finding_status_is_closed() -> None:
    with pytest.raises(ValidationError):
        AgentFinding(agent="a", status="maybe", summary="s", confidence=0.5)  # type: ignore[arg-type]


def test_response_mode_is_closed() -> None:
    with pytest.raises(ValidationError):
        ResponseDraft(mode="send_it", audience=Role.CUSTOMER, text="x")  # type: ignore[arg-type]


def test_risk_tier_values_match_the_policy_table() -> None:
    assert int(RiskTier.AUTO) == 0
    assert int(RiskTier.AUTO_NOTIFY) == 1
    assert int(RiskTier.DRAFT_APPROVAL) == 2
    assert int(RiskTier.ESCALATE_ONLY) == 3


def test_intent_covers_exactly_the_nine_specified() -> None:
    assert {i.value for i in Intent} == {
        "SALES_INQUIRY", "BOOKING", "DOCUMENTATION", "PAYMENT", "CONSTRUCTION_STATUS",
        "MAINTENANCE", "CONTRACTOR_UPDATE", "COMPLAINT_ESCALATION", "OTHER",
    }


def test_role_covers_exactly_the_nine_specified() -> None:
    assert {r.value for r in Role} == {
        "public_lead", "customer", "resident", "broker", "contractor",
        "sales_staff", "site_engineer", "legal_finance", "manager",
    }


def test_priority_is_p1_to_p4() -> None:
    assert [p.value for p in Priority] == ["P1", "P2", "P3", "P4"]


def test_chunk_converts_to_a_citation_without_losing_provenance() -> None:
    chunk = Chunk(
        chunk_id="c1",
        source_id="PS-AUR-2026-07",
        source_name="Aurora price list",
        collection="pricing_sheets",  # type: ignore[arg-type]
        section_heading="2BHK",
        content="text",
        effective_date=date(2026, 7, 14),
        is_stale=True,
    )
    citation = chunk.to_citation()
    assert isinstance(citation, Citation)
    assert citation.source_id == "PS-AUR-2026-07"
    assert citation.effective_date == date(2026, 7, 14)
    assert citation.is_stale is True


def test_escalation_decision_requires_a_rationale() -> None:
    with pytest.raises(ValidationError):
        EscalationDecision(required=True)  # type: ignore[call-arg]


def scope() -> AccessScope:
    return AccessScope(actor_id="CUST-4471", role=Role.CUSTOMER)


def test_case_state_separates_internal_findings() -> None:
    state = CaseState(
        case_id="CASE-1", channel=Channel.WEB_CHAT, scope=scope(), raw_input="x", masked_input="x"
    )
    state.findings = [
        AgentFinding(agent="public", status="ok", summary="s", confidence=0.9, structured={"a": 1}),
        AgentFinding(
            agent="private", status="ok", summary="s", confidence=0.9, structured={"a": 1},
            internal_only=True,
        ),
    ]
    assert [f.agent for f in state.external_findings()] == ["public"]
    assert len(state.findings) == 2, "external_findings must not mutate the list"


def test_min_confidence_includes_the_classification() -> None:
    state = CaseState(
        case_id="CASE-1", channel=Channel.WEB_CHAT, scope=scope(), raw_input="x", masked_input="x"
    )
    state.classification = Classification(intent=Intent.OTHER, confidence=0.4)
    state.findings = [AgentFinding(agent="a", status="ok", summary="s", confidence=0.9)]
    assert state.min_confidence() == 0.4


def test_audience_follows_the_scope_role() -> None:
    state = CaseState(
        case_id="CASE-1", channel=Channel.WEB_CHAT, scope=scope(), raw_input="x", masked_input="x"
    )
    assert state.audience is Role.CUSTOMER
