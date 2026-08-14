"""Routing is a table. These tests read it back."""

from __future__ import annotations

import pytest

from core.enums import Intent, Role
from core.models import Classification
from orchestration import router


@pytest.mark.parametrize(
    "intent,expected",
    [
        (Intent.SALES_INQUIRY, ["property_info"]),
        (Intent.DOCUMENTATION, ["documentation"]),
        (Intent.PAYMENT, ["payments"]),
        (Intent.CONSTRUCTION_STATUS, ["construction"]),
        (Intent.MAINTENANCE, ["maintenance"]),
        (Intent.CONTRACTOR_UPDATE, ["contractor"]),
    ],
)
def test_intent_routes_to_expected_agents(intent: Intent, expected: list[str]) -> None:
    plan = router.plan(Classification(intent=intent, confidence=0.9), Role.CUSTOMER, "question")
    assert plan.agents == expected
    assert plan.triage is False


def test_low_confidence_goes_to_triage_without_running_agents() -> None:
    plan = router.plan(Classification(intent=Intent.SALES_INQUIRY, confidence=0.4), Role.CUSTOMER, "hm")
    assert plan.triage is True
    assert plan.agents == []
    assert "below the" in plan.reason


def test_secondary_intent_adds_its_agents() -> None:
    plan = router.plan(
        Classification(
            intent=Intent.DOCUMENTATION, secondary_intent=Intent.PAYMENT, confidence=0.9
        ),
        Role.CUSTOMER,
        "documents and payment",
    )
    assert plan.agents == ["documentation", "payments"]


def test_booking_intent_covers_documents_and_payments() -> None:
    plan = router.plan(Classification(intent=Intent.BOOKING, confidence=0.9), Role.CUSTOMER, "booking")
    assert set(plan.agents) == {"documentation", "payments"}


def test_sales_followup_phrasing_adds_the_followup_agent() -> None:
    plan = router.plan(
        Classification(intent=Intent.SALES_INQUIRY, confidence=0.9),
        Role.SALES_STAFF,
        "who should I follow up with today",
    )
    assert plan.agents[0] == "followup"


def test_followup_is_not_offered_to_customers() -> None:
    plan = router.plan(
        Classification(intent=Intent.SALES_INQUIRY, confidence=0.9),
        Role.CUSTOMER,
        "who should I follow up with today",
    )
    assert "followup" not in plan.agents


def test_contractor_role_always_reaches_the_contractor_agent() -> None:
    plan = router.plan(
        Classification(intent=Intent.CONSTRUCTION_STATUS, confidence=0.9),
        Role.CONTRACTOR,
        "when is the slab due",
    )
    assert plan.agents == ["contractor"]


def test_complaint_intent_runs_no_specialist() -> None:
    plan = router.plan(
        Classification(intent=Intent.COMPLAINT_ESCALATION, confidence=0.9), Role.CUSTOMER, "refund"
    )
    assert plan.agents == []
    assert plan.triage is False


def test_missing_classification_is_triage() -> None:
    plan = router.plan(None, Role.CUSTOMER, "anything")
    assert plan.triage is True
