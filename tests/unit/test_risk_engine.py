"""Risk tiering. Pure inputs, asserted outputs, no mocking required.

These cases are the PRD's escalation matrix read back as tests. If a rule changes
in YAML, a test here should fail — that coupling is intentional.
"""

from __future__ import annotations

import pytest

from core.enums import EscalationType, Intent, RiskTier, Role
from core.models import AgentFinding, Classification
from orchestration import risk_engine


def classification(intent: Intent = Intent.CONSTRUCTION_STATUS, confidence: float = 0.9):
    return Classification(intent=intent, confidence=confidence)


def ok_finding(agent: str = "construction", confidence: float = 0.9, internal: bool = False):
    return AgentFinding(
        agent=agent,
        status="ok",
        summary="grounded summary",
        structured={"pct_complete": 62.0},
        confidence=confidence,
        internal_only=internal,
    )


@pytest.mark.parametrize(
    "text,expected_type",
    [
        ("I want a refund for this booking", EscalationType.REFUND_DEMAND),
        ("my lawyer will send you a legal notice", EscalationType.LEGAL_NOTICE),
        ("I have been wrongly charged on the last demand note", EscalationType.PAYMENT_DISPUTE),
        ("what discount can you give me", EscalationType.DISCOUNT_REQUEST),
        ("I am going to post this on social media", EscalationType.MEDIA_THREAT),
        ("I will file a RERA complaint", EscalationType.REGULATORY_COMPLAINT),
        ("why has possession moved again", EscalationType.POSSESSION_DATE_DISPUTE),
    ],
)
def test_tier_three_triggers(text: str, expected_type: EscalationType) -> None:
    result = risk_engine.assess(
        text=text,
        role=Role.CUSTOMER,
        classification=classification(Intent.COMPLAINT_ESCALATION),
        findings=[ok_finding()],
    )
    assert result.tier is RiskTier.ESCALATE_ONLY
    assert result.escalation_type is expected_type
    assert result.owner_team
    assert result.sla_hours
    assert result.acknowledgement_only is True


def test_safety_critical_finding_forces_tier_three() -> None:
    finding = AgentFinding(
        agent="maintenance",
        status="ok",
        summary="gas smell reported",
        structured={"safety_critical": True, "safety_signal": "Gas leak or suspected gas escape"},
        confidence=0.95,
    )
    result = risk_engine.assess(
        text="I can smell gas",
        role=Role.RESIDENT,
        classification=classification(Intent.MAINTENANCE),
        findings=[finding],
    )
    assert result.tier is RiskTier.ESCALATE_ONLY
    assert result.escalation_type is EscalationType.SAFETY_INCIDENT


def test_internal_finding_for_external_audience_is_at_least_tier_two() -> None:
    result = risk_engine.assess(
        text="what is the status of my tower",
        role=Role.CUSTOMER,
        classification=classification(),
        findings=[ok_finding(internal=True)],
    )
    assert result.tier is RiskTier.DRAFT_APPROVAL


def test_internal_finding_for_internal_audience_stays_low() -> None:
    result = risk_engine.assess(
        text="status of tower B",
        role=Role.MANAGER,
        classification=classification(),
        findings=[ok_finding(internal=True)],
    )
    assert int(result.tier) <= 1


def test_low_confidence_routes_to_a_human() -> None:
    result = risk_engine.assess(
        text="tower b",
        role=Role.CUSTOMER,
        classification=classification(confidence=0.42),
        findings=[ok_finding()],
    )
    assert result.tier is RiskTier.DRAFT_APPROVAL
    assert result.escalation_type is EscalationType.LOW_CONFIDENCE


def test_conflicting_sources_escalate() -> None:
    conflict = AgentFinding(
        agent="documentation", status="conflict", summary="two checklists disagree", confidence=0.8
    )
    result = risk_engine.assess(
        text="what documents do I need",
        role=Role.CUSTOMER,
        classification=classification(Intent.DOCUMENTATION),
        findings=[conflict],
    )
    assert result.tier is RiskTier.DRAFT_APPROVAL
    assert result.escalation_type is EscalationType.SOURCE_CONFLICT


def test_missing_data_escalates() -> None:
    gap = AgentFinding(
        agent="payments", status="insufficient_data", summary="no schedule visible", confidence=0.0
    )
    result = risk_engine.assess(
        text="what is my outstanding amount",
        role=Role.CUSTOMER,
        classification=classification(Intent.PAYMENT),
        findings=[gap],
    )
    assert result.tier is RiskTier.DRAFT_APPROVAL
    assert result.escalation_type is EscalationType.MISSING_DATA


def test_repeated_contact_is_tier_two() -> None:
    result = risk_engine.assess(
        text="checking on my documents once more",
        role=Role.CUSTOMER,
        classification=classification(Intent.DOCUMENTATION),
        findings=[ok_finding("documentation")],
        prior_contacts=3,
    )
    assert result.tier is RiskTier.DRAFT_APPROVAL
    assert result.escalation_type is EscalationType.REPEATED_CONTACT


def test_clean_informational_case_is_tier_zero() -> None:
    result = risk_engine.assess(
        text="what is the construction status of tower B",
        role=Role.CUSTOMER,
        classification=classification(),
        findings=[ok_finding()],
    )
    assert result.tier is RiskTier.AUTO
    assert result.requires_human is False


def test_ambiguity_resolves_upward_not_downward() -> None:
    """A refund demand with high confidence is still tier 3, not tier 0."""
    result = risk_engine.assess(
        text="I want a refund and also what is my document status",
        role=Role.CUSTOMER,
        classification=classification(Intent.DOCUMENTATION, confidence=0.95),
        findings=[ok_finding("documentation")],
    )
    assert result.tier is RiskTier.ESCALATE_ONLY


def test_assessment_is_deterministic() -> None:
    kwargs = {
        "text": "I want a refund",
        "role": Role.CUSTOMER,
        "classification": classification(Intent.COMPLAINT_ESCALATION),
        "findings": [ok_finding()],
    }
    first = risk_engine.assess(**kwargs)
    second = risk_engine.assess(**kwargs)
    assert (first.tier, first.escalation_type, first.triggers) == (
        second.tier,
        second.escalation_type,
        second.triggers,
    )
