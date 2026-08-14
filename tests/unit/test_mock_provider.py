"""The offline provider must satisfy every prompt's declared schema.

This is the pairing test referenced in `llm/mock_provider.py`: when a prompt's
schema changes, this file fails, which is the reminder to update the handler.
"""

from __future__ import annotations

import json

import pytest

from governance.policy_registry import REQUIRED_PROMPTS
from llm import mock_provider


VARIABLES = {
    "classification": {"request": "do you have a 2bhk under 85 lakhs", "channel": "chat"},
    "maintenance": {"request": "water is leaking from the bathroom ceiling"},
    "property_info": {
        "facts": {
            "query": {"config": "2BHK"},
            "match_count": 2,
            "units": [
                {
                    "unit_id": "BW-A-0304",
                    "project_name": "Aurora Heights",
                    "tower_name": "Tower A",
                    "city": "Bengaluru",
                    "locality": "Whitefield",
                    "config": "2BHK",
                    "carpet_area": 1120,
                    "floor": 3,
                    "facing": "east",
                    "all_in_price": 8100000,
                }
            ],
            "price_ref": "PS-AUR-2026-07",
            "price_effective_date": "2026-07-14",
        },
        "context": "(none)",
        "request": "any 2bhk",
    },
    "documentation": {
        "facts": {"stage_label": "registration", "missing": ["stamp_duty_receipt"], "expired": [], "submitted": ["pan_card"]},
        "context": "(none)",
        "request": "what is pending",
    },
    "construction_customer": {
        "facts": {"tower_name": "Tower B", "project_name": "Aurora Heights", "pct_complete": 62.0},
        "context": "(none)",
        "request": "status",
    },
    "construction_internal": {
        "facts": {"tower_name": "Tower B", "project_name": "Aurora Heights", "pct_complete": 62.0,
                  "milestones_complete": 5, "milestones_total": 8},
        "context": "(none)",
        "request": "status",
    },
    "contractor": {
        "facts": {"detected_category": "material_shortage", "severity": "high",
                  "impacted_milestones": ["MS-3"], "commitment_requested": True},
        "context": "(none)",
        "request": "cement stock is zero, when will you pay us",
    },
    "escalation_brief": {
        "facts": {"case_id": "CASE-1", "channel": "chat", "actor_role": "customer",
                  "intent": "COMPLAINT_ESCALATION", "risk_tier": 3,
                  "escalation_type": "refund_demand", "owner_team": "legal_finance",
                  "sla_hours": 24, "triggers": ["refund"], "findings": [], "gaps": []},
        "request": "I want a refund",
    },
    "response_customer": {"findings": [], "request": "anything"},
    "response_broker": {"findings": [], "request": "anything"},
    "response_contractor": {"findings": [], "request": "anything"},
    "response_internal": {"findings": [], "request": "anything"},
    "repair": {"schema": "{}", "error": "bad json", "output": "{'a': 1,}"},
}


@pytest.mark.parametrize("prompt_id", REQUIRED_PROMPTS)
def test_every_required_prompt_has_a_handler(prompt_id: str) -> None:
    assert prompt_id in mock_provider.HANDLERS


@pytest.mark.parametrize("prompt_id", REQUIRED_PROMPTS)
def test_output_is_valid_json(prompt_id: str) -> None:
    raw = mock_provider.generate(prompt_id, VARIABLES[prompt_id])
    assert isinstance(json.loads(raw), dict)


def test_classification_validates_against_the_agent_schema() -> None:
    from agents.classification import ClassificationOutput

    raw = mock_provider.generate("classification", VARIABLES["classification"])
    parsed = ClassificationOutput.model_validate(json.loads(raw))
    assert parsed.intent.value == "SALES_INQUIRY"
    assert 0.0 <= parsed.confidence <= 1.0


def test_maintenance_validates_and_quotes_severity_words_verbatim() -> None:
    from agents.maintenance import MaintenanceOutput

    raw = mock_provider.generate("maintenance", VARIABLES["maintenance"])
    parsed = MaintenanceOutput.model_validate(json.loads(raw))
    assert parsed.category.value == "plumbing"
    # The deterministic priority rules match on these strings, so a paraphrase
    # would break the rule engine downstream.
    assert any(signal in VARIABLES["maintenance"]["request"] for signal in parsed.severity_signals)


def test_grievance_beats_topic_in_classification() -> None:
    raw = mock_provider.generate(
        "classification",
        {"request": "why has possession moved again, who is accountable for this", "channel": "email"},
    )
    assert json.loads(raw)["intent"] == "COMPLAINT_ESCALATION"


def test_short_input_lowers_confidence() -> None:
    terse = json.loads(mock_provider.generate("classification", {"request": "price?", "channel": "chat"}))
    verbose = json.loads(
        mock_provider.generate(
            "classification",
            {"request": "what is the price list for a 2bhk at Aurora Heights in Whitefield", "channel": "chat"},
        )
    )
    assert terse["confidence"] < verbose["confidence"]


def test_unknown_prompt_raises_rather_than_returning_empty() -> None:
    with pytest.raises(KeyError):
        mock_provider.generate("not_a_prompt", {})


def test_generation_is_deterministic() -> None:
    args = ("classification", VARIABLES["classification"])
    assert mock_provider.generate(*args) == mock_provider.generate(*args)


def test_response_with_no_usable_findings_refuses() -> None:
    raw = json.loads(mock_provider.generate("response_customer", {"findings": [], "request": "x"}))
    assert raw["next_action"] == "human_handoff"
    assert raw["confidence"] < 0.7
