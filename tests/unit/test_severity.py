"""Deterministic severity assignment.

The safety-critical block is the reason this module exists in code rather than in a
prompt. The PRD asks for 100% recall on these signals, so the test asserts every
curated phrasing lands on P1 — a property you can only hold with a function.
"""

from __future__ import annotations

import pytest

from core.enums import MaintenanceCategory, Priority
from governance import severity


SAFETY_PHRASINGS = [
    ("I can smell gas near the kitchen pipe", "gas_leak"),
    ("there is an lpg leak in the utility area", "gas_leak"),
    ("the socket is sparking when I plug anything in", "electrical_hazard"),
    ("there is a burning smell from the DB box", "electrical_hazard"),
    ("I got an electric shock from the geyser switch", "electrical_hazard"),
    ("a structural crack has appeared across the beam", "structural_crack"),
    ("the crack has widened since last month", "structural_crack"),
    ("my mother is stuck inside lift number 2", "lift_entrapment"),
    ("two people are trapped in the lift right now", "lift_entrapment"),
    ("the lift stopped between floors with someone inside", "lift_entrapment"),
    ("the lift door will not open and my child is inside", "lift_entrapment"),
    ("we cannot get out of the lift", "lift_entrapment"),
]


@pytest.mark.parametrize("text,expected_class", SAFETY_PHRASINGS)
def test_safety_signals_force_p1(text: str, expected_class: str) -> None:
    decision = severity.assign_priority(MaintenanceCategory.CIVIL, text)
    assert decision.priority is Priority.P1
    assert decision.safety_critical is True
    assert decision.safety_class == expected_class
    assert decision.on_call_team, "a safety-critical case must name an on-call team"


def test_safety_detection_is_category_independent() -> None:
    """A miscategorised complaint must still hit the hazard path."""
    text = "smell of gas in the corridor"
    for category in MaintenanceCategory:
        decision = severity.assign_priority(category, text)
        assert decision.priority is Priority.P1, f"missed hazard when category={category.value}"


@pytest.mark.parametrize(
    "text",
    [
        "the wall paint is peeling in the bedroom",
        "someone else keeps parking in my slot",
        "the corridor light is not working",
    ],
)
def test_benign_complaints_are_not_safety_critical(text: str) -> None:
    decision = severity.assign_priority(MaintenanceCategory.COMMON_AREA, text)
    assert decision.safety_critical is False
    assert decision.priority is not Priority.P1


def test_active_water_ingress_is_p2() -> None:
    decision = severity.assign_priority(
        MaintenanceCategory.PLUMBING, "water is leaking from the bathroom ceiling and spreading"
    )
    assert decision.priority is Priority.P2
    assert decision.matched_rule == "R03"
    assert decision.assigned_team == "facility_plumbing"


def test_sla_and_response_hours_come_from_policy() -> None:
    decision = severity.assign_priority(MaintenanceCategory.LIFT, "the lift is out of service")
    assert decision.sla_hours == 24
    assert decision.response_hours == 4
    assert decision.policy_version


def test_unmatched_complaint_falls_to_category_default() -> None:
    decision = severity.assign_priority(MaintenanceCategory.PARKING, "question about my parking slot")
    assert decision.matched_rule is None
    assert decision.priority is Priority.P4
    assert "default" in decision.reason


def test_rationale_names_the_rule_that_fired() -> None:
    decision = severity.assign_priority(MaintenanceCategory.PLUMBING, "the drain is choked")
    assert "R03" in decision.rationale()
    assert "choked" in decision.rationale()
