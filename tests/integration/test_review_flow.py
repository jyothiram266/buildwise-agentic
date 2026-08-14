"""The human-in-the-loop path, end to end."""

from __future__ import annotations

import uuid

import pytest

from core.enums import RejectionReason, ReviewAction, RiskTier, Role
from core.errors import PolicyViolationError
from db import pool
from governance import review_queue

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def _seed_case(case_id: str) -> None:
    """Insert the case this test operates on.

    No `ON CONFLICT DO NOTHING`: swallowing a conflict turns leftover state into a
    silent no-op, which is precisely how two tests in this file came to fail on
    preconditions they believed they had set. Case state is truncated per test
    (see conftest), so a conflict here means a genuine bug and should raise.
    """
    await pool.execute(
        """
        INSERT INTO cases (case_id, actor_id, role, channel, masked_input, status, risk_tier)
        VALUES ($1,'CUST-4471','customer','web_chat','test input','awaiting_approval',2)
        """,
        case_id,
    )


async def test_approve_issues_a_single_use_token() -> None:
    case_id = "CASE-REVIEW-APPROVE"
    await _seed_case(case_id)
    item = await review_queue.enqueue(
        case_id=case_id,
        risk_tier=RiskTier.DRAFT_APPROVAL,
        audience=Role.CUSTOMER,
        original_request="test input",
        reasoning_summary="tier 2 because the audience is external",
        proposed_response="Here is the position on your tower.",
        confidence=0.82,
    )
    result = await review_queue.act(item.review_id, ReviewAction.APPROVE, "STF-MGR-01")
    assert result["status"] == "approved"
    assert result["approval_token"]

    row = await pool.fetchrow(
        "SELECT consumed FROM approval_tokens WHERE token = $1", result["approval_token"]
    )
    assert row is not None and row["consumed"] is False  # consumed on use, not on issue


async def test_a_second_decision_is_refused() -> None:
    case_id = "CASE-REVIEW-DOUBLE"
    await _seed_case(case_id)
    item = await review_queue.enqueue(
        case_id=case_id,
        risk_tier=RiskTier.DRAFT_APPROVAL,
        audience=Role.CUSTOMER,
        original_request="test input",
        reasoning_summary="reason",
        proposed_response="draft",
        confidence=0.8,
    )
    await review_queue.act(item.review_id, ReviewAction.APPROVE, "STF-MGR-01")
    with pytest.raises(PolicyViolationError):
        await review_queue.act(item.review_id, ReviewAction.APPROVE, "STF-MGR-01")


async def test_non_approver_role_is_refused() -> None:
    case_id = "CASE-REVIEW-ROLE"
    await _seed_case(case_id)
    item = await review_queue.enqueue(
        case_id=case_id,
        risk_tier=RiskTier.DRAFT_APPROVAL,
        audience=Role.CUSTOMER,
        original_request="test input",
        reasoning_summary="reason",
        proposed_response="draft",
        confidence=0.8,
    )
    with pytest.raises(PolicyViolationError):
        await review_queue.act(item.review_id, ReviewAction.APPROVE, "CUST-4471")


async def test_rejection_requires_a_reason_from_the_fixed_set() -> None:
    case_id = "CASE-REVIEW-REJECT"
    await _seed_case(case_id)
    item = await review_queue.enqueue(
        case_id=case_id,
        risk_tier=RiskTier.DRAFT_APPROVAL,
        audience=Role.CUSTOMER,
        original_request="test input",
        reasoning_summary="reason",
        proposed_response="draft",
        confidence=0.8,
    )
    with pytest.raises(PolicyViolationError):
        await review_queue.act(item.review_id, ReviewAction.REJECT, "STF-MGR-01")

    result = await review_queue.act(
        item.review_id,
        ReviewAction.REJECT,
        "STF-MGR-01",
        rejection_reason=RejectionReason.WRONG_TONE,
    )
    assert result["status"] == "rejected"


async def test_edit_and_send_records_the_edited_text() -> None:
    case_id = "CASE-REVIEW-EDIT"
    await _seed_case(case_id)
    item = await review_queue.enqueue(
        case_id=case_id,
        risk_tier=RiskTier.DRAFT_APPROVAL,
        audience=Role.CUSTOMER,
        original_request="test input",
        reasoning_summary="reason",
        proposed_response="original draft",
        confidence=0.8,
    )
    result = await review_queue.act(
        item.review_id, ReviewAction.EDIT_AND_SEND, "STF-MGR-01", edited_text="human wording"
    )
    assert result["sent_text"] == "human wording"
    case = await pool.fetchrow("SELECT response_text, response_mode FROM cases WHERE case_id = $1", case_id)
    assert case["response_text"] == "human wording"
    assert case["response_mode"] == "human_edited"


async def test_override_stats_expose_the_reason_distribution() -> None:
    stats = await review_queue.override_stats(window_days=1)
    assert "override_rate" in stats
    assert stats["target"] == 0.25
    assert isinstance(stats["reasons"], list)


async def test_trace_is_append_only() -> None:
    """The guarantee is enforced by the database, so it survives application bugs."""
    import asyncpg

    from governance import audit

    case_id = "CASE-APPEND-ONLY"
    await _seed_case(case_id)
    trace_id = await audit.record(case_id, "test", inputs={"a": 1}, output={"b": 2})
    with pytest.raises(asyncpg.PostgresError):
        await pool.execute("UPDATE agent_trace SET agent = 'tampered' WHERE trace_id = $1", trace_id)
    with pytest.raises(asyncpg.PostgresError):
        await pool.execute("DELETE FROM agent_trace WHERE trace_id = $1", trace_id)


async def test_escalated_case_cannot_be_closed_autonomously() -> None:
    """FR-ESC-5: an open escalation blocks closure, for humans and code alike."""
    from governance import sla

    case_id = "CASE-ESC-CLOSE"
    # A fresh id per run. The original used a fixed id with ON CONFLICT DO NOTHING,
    # so a resolved row from a previous run silently survived and the insert was a
    # no-op — the test then failed on a precondition it thought it had established.
    esc_id = f"ESC-CLOSE-{uuid.uuid4().hex[:8]}"
    await _seed_case(case_id)
    await pool.execute(
        """
        INSERT INTO escalations (esc_id, case_id, type, owner_team, sla_hours, sla_due, brief)
        VALUES ($3, $1, 'refund_demand', 'legal_finance', 24, $2, 'brief')
        """,
        case_id,
        sla.due_at(24),
        esc_id,
    )

    assert await review_queue.has_open_escalation(case_id) is True
    with pytest.raises(PolicyViolationError):
        await review_queue.close_case(case_id, "STF-MGR-01", "trying to close early")

    # Resolving the escalation is a human act, and only then can the case close.
    await review_queue.resolve_escalation(esc_id, "STF-LEG-01", "refund declined, explained")
    assert await review_queue.has_open_escalation(case_id) is False

    result = await review_queue.close_case(case_id, "STF-MGR-01", "resolved with the customer")
    assert result["status"] == "closed"

    row = await pool.fetchrow("SELECT status, closed_at FROM cases WHERE case_id = $1", case_id)
    assert row["status"] == "closed"
    assert row["closed_at"] is not None


async def test_non_approver_cannot_close_a_case() -> None:
    case_id = "CASE-CLOSE-ROLE"
    await _seed_case(case_id)
    with pytest.raises(PolicyViolationError):
        await review_queue.close_case(case_id, "CUST-4471", "customer closing their own case")


async def test_resolving_an_escalation_twice_is_refused() -> None:
    from governance import sla

    case_id = "CASE-ESC-TWICE"
    esc_id = f"ESC-TWICE-{uuid.uuid4().hex[:8]}"
    await _seed_case(case_id)
    await pool.execute(
        """
        INSERT INTO escalations (esc_id, case_id, type, owner_team, sla_hours, sla_due, brief)
        VALUES ($3, $1, 'legal_notice', 'legal_finance', 8, $2, 'brief')
        """,
        case_id,
        sla.due_at(8),
        esc_id,
    )
    await review_queue.resolve_escalation(esc_id, "STF-LEG-01", "handled")
    with pytest.raises(PolicyViolationError):
        await review_queue.resolve_escalation(esc_id, "STF-LEG-01", "handled again")


async def test_jsonb_columns_round_trip_as_objects() -> None:
    """JSONB must read back as an object, not as a quoted JSON string.

    A regression test for a silent bug: every pooled connection registers a JSON
    codec, so a caller that also called `json.dumps` double-encoded the value. Reads
    then returned a string where a dict belonged. Nothing raised — the audit trail
    was simply wrong when anyone looked at it, which is the worst kind of defect in a
    table whose whole purpose is being looked at.
    """
    from governance import audit

    case_id = "CASE-JSONB-ROUNDTRIP"
    await _seed_case(case_id)
    payload = {"decision": "tier_2", "triggers": ["confidence"], "nested": {"n": 1}}
    await audit.record(case_id, "jsonb_probe", inputs={"x": 1}, output=payload)

    row = await pool.fetchrow(
        "SELECT output FROM agent_trace WHERE case_id = $1 AND agent = 'jsonb_probe'", case_id
    )
    assert isinstance(row["output"], dict), f"expected dict, got {type(row['output']).__name__}"
    assert row["output"]["triggers"] == ["confidence"]
    assert row["output"]["nested"]["n"] == 1


async def test_case_findings_round_trip_as_a_list() -> None:
    from core.enums import Channel
    from governance import rbac
    from orchestration.graph import run_case

    scope = await rbac.scope_for_actor("CUST-4471")
    state = await run_case("What documents do I need?", scope, channel=Channel.WEB_CHAT)
    row = await pool.fetchrow(
        "SELECT findings, entities, response_citations FROM cases WHERE case_id = $1",
        state.case_id,
    )
    assert isinstance(row["findings"], list)
    assert isinstance(row["entities"], dict)
    assert isinstance(row["response_citations"], list)
