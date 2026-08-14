"""The disclosure gate: the second, independent check before anything is sent."""

from __future__ import annotations

from core.enums import Role
from core.models import AgentFinding
from agents.response import check_disclosure


def finding(structured: dict, internal: bool = False) -> AgentFinding:
    return AgentFinding(
        agent="construction",
        status="ok",
        summary="summary",
        structured=structured,
        confidence=0.9,
        internal_only=internal,
    )


def test_clean_customer_text_passes() -> None:
    result = check_disclosure(
        "Tower B is at 62% milestone completion as certified on 2026-07-30.",
        Role.CUSTOMER,
        [finding({"pct_complete": 62.0, "last_certified": "2026-07-30"})],
    )
    assert result.passed is True


def test_commitment_language_is_blocked() -> None:
    result = check_disclosure(
        "We guarantee possession by March and rest assured it will not slip again.",
        Role.CUSTOMER,
        [finding({"pct_complete": 62.0})],
    )
    assert result.passed is False
    assert result.downgraded_to == "draft_for_approval"


def test_unapproved_possession_date_is_blocked() -> None:
    result = check_disclosure(
        "The revised handover is now 2027-09-30.",
        Role.CUSTOMER,
        [finding({"unapproved_revised_possession": "2027-09-30"})],
    )
    assert result.passed is False
    assert any("unapproved" in violation for violation in result.violations)


def test_approved_date_is_allowed() -> None:
    result = check_disclosure(
        "The possession date on record is 2027-03-31.",
        Role.CUSTOMER,
        [finding({"approved_revised_possession": "2027-03-31"})],
    )
    assert result.passed is True


def test_internal_terms_are_blocked_for_customers() -> None:
    result = check_disclosure(
        "The vendor has a payment dispute which is holding up the work.",
        Role.CUSTOMER,
        [finding({"pct_complete": 62.0})],
    )
    assert result.passed is False


def test_ungrounded_amount_is_blocked() -> None:
    result = check_disclosure(
        "Your outstanding balance is INR 4,50,000.",
        Role.CUSTOMER,
        [finding({"total_overdue": 275000})],
    )
    assert result.passed is False


def test_grounded_amount_passes() -> None:
    result = check_disclosure(
        "Your overdue amount is INR 275000 against the schedule.",
        Role.CUSTOMER,
        [finding({"total_overdue": 275000})],
    )
    assert result.passed is True


def test_delay_speculation_is_blocked() -> None:
    """FR-CON-3: unconfirmed delay speculation must not reach a customer."""
    result = check_disclosure(
        "Possession may slip to March, internally we are anticipating a further delay.",
        Role.CUSTOMER,
        [finding({"pct_complete": 62.0})],
    )
    assert result.passed is False


def test_safety_incident_detail_is_blocked() -> None:
    """FR-CON-3: a customer hears that a hazard is handled, not the injury detail."""
    result = check_disclosure(
        "A worker was injured during the slab work and the incident report is with EHS.",
        Role.CUSTOMER,
        [finding({"pct_complete": 62.0})],
    )
    assert result.passed is False


def test_cost_data_is_blocked() -> None:
    result = check_disclosure(
        "The internal cost per square foot has risen, causing a budget overrun.",
        Role.CUSTOMER,
        [finding({"pct_complete": 62.0})],
    )
    assert result.passed is False


def test_contractor_dispute_is_blocked() -> None:
    result = check_disclosure(
        "There is a contractor dispute over the RA bill holding up the work.",
        Role.CUSTOMER,
        [finding({"pct_complete": 62.0})],
    )
    assert result.passed is False


def test_internal_audience_is_not_gated() -> None:
    """Internal readers are cleared for cost and vendor detail by definition."""
    result = check_disclosure(
        "internal only — vendor dispute with a cost overrun of INR 900000.",
        Role.MANAGER,
        [finding({}, internal=True)],
    )
    assert result.passed is True
