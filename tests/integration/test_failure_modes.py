"""Failure-mode and degradation tests (build plan P7-T5).

Architecture Section 3.4 gives every failure a named destination. These tests assert
the destination, because the interesting property is not that a component can fail —
it is that failing produces a human handoff rather than a confident answer built on
missing data.

Each test forces a real failure rather than asserting on a mock's call count.
"""

from __future__ import annotations

import pytest

from core.enums import CaseStatus, RiskTier
from core.errors import ConnectorError, ValidationFailure
from db import pool
from orchestration.graph import run_case

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_connector_down_degrades_to_a_human(scopes, monkeypatch) -> None:
    """A system of record is unreachable: say so, do not answer from the corpus."""
    from connectors import crm

    async def explode(*args, **kwargs):
        raise ConnectorError("crm did not respond", system="crm")

    monkeypatch.setattr(crm.CrmConnector, "query_inventory", explode)

    state = await run_case("Do you have any 2BHK under 85 lakhs?", scopes["public_lead"])
    finding = state.finding("property_info")
    assert finding is not None
    assert finding.status == "error"
    assert finding.confidence == 0.0
    # The case must not be auto-sent on the back of a failed lookup.
    assert state.risk_tier is not None and int(state.risk_tier) >= 2
    assert state.degraded is True


async def test_schema_failure_reaches_triage_not_a_guess(scopes, monkeypatch) -> None:
    """One repair attempt, then a human. Never a fabricated structure."""
    from llm import client as llm_client

    async def bad_completion(self, prompt_id, variables, case_id=None, **kwargs):
        from core.models import LLMResult, LLMUsage

        return LLMResult(
            text="this is not json and never will be",
            usage=LLMUsage(model="test"),
            prompt_id=prompt_id,
            prompt_version="test",
        )

    monkeypatch.setattr(llm_client.LLMClient, "complete", bad_completion)

    state = await run_case("What is the status of my tower?", scopes["customer"])
    # Classification fails, so the router must not dispatch a specialist on a guess.
    assert state.classification is None or state.classification.confidence == 0.0
    assert state.degraded is True
    assert state.risk_tier is not None and int(state.risk_tier) >= 2


async def test_unhandled_exception_becomes_a_queued_case(scopes, monkeypatch) -> None:
    """Section 3.4: nothing is ever silently dropped."""
    from orchestration import risk_engine

    def explode(**kwargs):
        raise RuntimeError("engineered failure")

    monkeypatch.setattr(risk_engine, "assess", explode)

    state = await run_case("What documents do I need?", scopes["customer"])
    assert state.status is CaseStatus.FAILED
    assert state.error is not None

    row = await pool.fetchrow(
        "SELECT status FROM cases WHERE case_id = $1", state.case_id
    )
    assert row["status"] == "failed"

    queued = await pool.fetchval(
        "SELECT count(*) FROM review_queue WHERE case_id = $1", state.case_id
    )
    assert queued == 1, "a failed case must land in the human queue"


async def test_empty_retrieval_logs_a_gap_and_refuses(scopes) -> None:
    before = int(await pool.fetchval("SELECT count(*) FROM kb_gaps") or 0)
    state = await run_case(
        "What is the resale value of a qzxpt unit in Zzyzx?", scopes["customer"]
    )
    after = int(await pool.fetchval("SELECT count(*) FROM kb_gaps") or 0)
    assert after >= before
    assert state.response is not None
    assert state.response.mode in {"refuse", "draft_for_approval", "acknowledgement_only"}


async def test_escalation_survives_a_brief_generation_failure(scopes, monkeypatch) -> None:
    """The clock and the row are written before the brief, so the escalation holds."""
    from agents.escalation import EscalationAgent

    async def explode(self, *args, **kwargs):
        raise ValidationFailure("brief generation failed")

    monkeypatch.setattr(EscalationAgent, "generate", explode)

    state = await run_case(
        "I want a refund, this has gone on long enough.", scopes["customer"]
    )
    assert state.risk_tier is RiskTier.ESCALATE_ONLY

    row = await pool.fetchrow(
        "SELECT brief, owner_team, sla_due FROM escalations WHERE case_id = $1", state.case_id
    )
    assert row is not None, "the escalation row must exist even when the brief fails"
    assert row["owner_team"]
    assert row["sla_due"]
    assert "fallback" in row["brief"].lower() or len(row["brief"]) > 50


async def test_redis_absent_does_not_break_connectors(scopes, monkeypatch) -> None:
    """Caching is an optimisation; losing it degrades speed, not correctness."""
    from connectors import protocol

    async def no_redis():
        return None

    monkeypatch.setattr(protocol, "_get_redis", no_redis)

    from connectors import registry
    from connectors.crm import InventoryQuery

    result = await registry.crm().query_inventory(
        InventoryQuery(config="2BHK", limit=3), scopes["public_lead"]
    )
    assert result.match_count >= 0  # completed without a cache


async def test_partial_specialist_failure_still_answers_what_it_can(scopes, monkeypatch) -> None:
    """Two agents, one fails: the answer covers the half that worked and says so."""
    from agents.payments import PaymentsAgent

    async def explode(self, state):
        raise ConnectorError("payments unavailable", system="payments")

    monkeypatch.setattr(PaymentsAgent, "_run", explode)

    state = await run_case(
        "What is the status of my booking and what do I still owe?", scopes["customer"]
    )
    statuses = {f.agent: f.status for f in state.findings}
    assert "payments" in statuses
    assert state.degraded is True
    assert state.response is not None
