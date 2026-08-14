"""The registry contract: prompts parse, versions resolve, placeholders are strict."""

from __future__ import annotations

import pytest

from core.errors import ConfigurationError
from governance.policy_registry import REQUIRED_PROMPTS, get_registry


def test_every_required_prompt_resolves() -> None:
    registry = get_registry()
    registry.validate_all(REQUIRED_PROMPTS)


def test_prompt_metadata_is_complete() -> None:
    for entry in get_registry().list_prompts():
        assert entry["version"]
        assert entry["agent"]
        assert entry["model_tier"] in {"small", "large"}


def test_unknown_prompt_raises_rather_than_defaulting() -> None:
    with pytest.raises(ConfigurationError):
        get_registry().get("prompt_that_does_not_exist")


def test_missing_variable_raises_instead_of_rendering_none() -> None:
    """A prompt with an empty context block is how ungrounded answers happen."""
    prompt = get_registry().get("property_info")
    with pytest.raises(ConfigurationError):
        prompt.render({"facts": {}})


def test_render_substitutes_all_placeholders() -> None:
    prompt = get_registry().get("classification")
    rendered = prompt.render({"request": "any 2bhk available", "channel": "chat"})
    assert "{{" not in rendered
    assert "any 2bhk available" in rendered


def test_policies_are_versioned() -> None:
    registry = get_registry()
    for policy_id in ("severity_matrix", "escalation_matrix", "warranty_policy"):
        assert registry.policy_version(policy_id) != "unversioned"


def test_escalation_matrix_types_match_the_enum() -> None:
    from core.enums import EscalationType

    declared = set(get_registry().policy("escalation_matrix")["types"])
    assert declared == {t.value for t in EscalationType}


def test_document_checklist_policy_is_loaded_and_versioned() -> None:
    policy = get_registry().policy("document_checklists")
    assert policy["version"]
    assert policy["stage_order"]
    for stage in policy["stage_order"]:
        assert policy["stages"][stage]["documents"], f"{stage} has no required documents"


def test_agent_stage_order_matches_the_policy() -> None:
    """Two copies of an ordered list will disagree eventually; this catches it."""
    from agents.documentation import STAGE_ORDER

    assert STAGE_ORDER == get_registry().policy("document_checklists")["stage_order"]


def test_every_checklist_type_exists_in_the_seed_documents() -> None:
    """A required type the DMS never issues would show as permanently missing."""
    import json
    from pathlib import Path

    from api.config import get_settings

    seed = Path(get_settings().corpus_dir).parent / "seed" / "documents.json"
    known = {d["type"] for d in json.loads(seed.read_text())}
    policy = get_registry().policy("document_checklists")
    for stage, spec in policy["stages"].items():
        for doc in spec["documents"]:
            assert doc["type"] in known, f"{stage}: {doc['type']} is not a document the DMS issues"
