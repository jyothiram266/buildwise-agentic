"""The eight user journeys from the PRD, run through the real graph.

These are the acceptance tests. Each one asserts the *behaviour the PRD asked
for*, not the wording — the wording comes from a model and is allowed to vary; the
tier, the routing, the citations and the refusals are not.

Requires Postgres, the mock connector service, and the ingested corpus:
    make bootstrap && make test
"""

from __future__ import annotations

import pytest

from core.enums import Channel, RiskTier
from orchestration.graph import run_case

pytestmark = [pytest.mark.integration, pytest.mark.anyio]


async def test_uj1_availability_with_budget(scopes) -> None:
    state = await run_case(
        "Do you have any 2BHK under 85 lakhs in Whitefield?", scopes["public_lead"]
    )
    finding = state.finding("property_info")
    assert finding is not None and finding.status == "ok"
    assert finding.structured["match_count"] > 0
    assert finding.citations, "an availability answer must cite the price source"
    # Tier 0 or 1: a grounded, cited availability answer to a prospect needs no human.
    # This depends on a clean case history for the actor — the repeated-contact rule
    # correctly raises the tier on a third contact in 24 hours, so conftest resets
    # case state between tests rather than this test asserting a looser bound.
    assert state.risk_tier is not None and int(state.risk_tier) <= 1, (
        f"expected tier 0/1, got {int(state.risk_tier)}: "
        f"{state.metadata.get('route', {}).get('reason')}"
    )


async def test_uj1_no_match_does_not_substitute(scopes) -> None:
    """Aurora has no 1BHK. The answer must say so and offer nothing in its place."""
    state = await run_case("Any 1BHK available at Aurora Heights?", scopes["public_lead"])
    finding = state.finding("property_info")
    assert finding is not None
    assert finding.structured["match_count"] == 0
    assert finding.structured["substitution_offered"] is False
    assert finding.structured["reason"] in {"config_not_offered", "no_availability", "not_launched"}


async def test_uj2_customer_status_is_customer_safe(scopes) -> None:
    state = await run_case("What is the construction status of my tower?", scopes["customer"])
    finding = state.finding("construction")
    assert finding is not None and finding.internal_only is False
    # An unapproved revision must not be present in the customer-facing structure.
    assert finding.structured.get("unapproved_revised_possession") is None
    assert state.response is not None


async def test_uj3_pending_documents_distinguishes_expired(scopes) -> None:
    state = await run_case(
        "What documents are still pending for my registration?", scopes["customer"]
    )
    finding = state.finding("documentation")
    assert finding is not None and finding.status == "ok"
    assert finding.structured["gap_count"] > 0
    # The seeded customer has both a pending item and an expired one.
    assert finding.structured["expired"] or finding.structured["missing"]


async def test_uj4_possession_dispute_is_acknowledgement_only(scopes) -> None:
    state = await run_case(
        "Why has my possession date moved again? I want a refund if this continues.",
        scopes["customer"],
        channel=Channel.EMAIL,
    )
    assert state.risk_tier is RiskTier.ESCALATE_ONLY
    assert state.response is not None
    assert state.response.mode == "acknowledgement_only"
    assert state.escalation is not None
    assert state.escalation.sla_hours and state.escalation.owner_team
    # No date and no commitment in an acknowledgement.
    assert "2027" not in state.response.text


async def test_uj5_engineer_note_produces_both_summaries(scopes) -> None:
    note = (
        "B blk slab 7 done 60%, curing on. steel short, vendor says 3 days. lift shaft "
        "measurement mismatch 40mm, told them to hold. possession may slip to Mar."
    )
    state = await run_case(note, scopes["site_engineer"])
    finding = state.finding("construction")
    assert finding is not None
    assert finding.internal_only is True
    assert finding.structured.get("customer_summary"), "UJ-5 needs a customer-safe version too"


async def test_uj6_contractor_blocker_gives_a_range_not_a_date(scopes) -> None:
    state = await run_case(
        "Cement supply has stopped at Tower B, we have zero stock. When will you release my payment?",
        scopes["contractor"],
    )
    finding = state.finding("contractor")
    assert finding is not None
    assert finding.internal_only is True
    assert finding.structured["commitment_requested"] is True
    assert finding.structured["commitment_made"] is False
    delay = finding.structured.get("delay_range_days")
    if delay:
        assert delay[0] <= delay[1], "a delay estimate must be a range"


async def test_uj7_leak_creates_a_ticket_with_sla(scopes) -> None:
    state = await run_case(
        "There is water leaking from the bathroom ceiling and it is spreading.", scopes["resident"]
    )
    finding = state.finding("maintenance")
    assert finding is not None and finding.status == "ok"
    assert finding.structured["category"] == "plumbing"
    assert finding.structured["priority"] == "P2"
    assert finding.structured["ticket_id"], "a maintenance complaint must produce a ticket"
    assert finding.structured["sla_due"]


async def test_uj7_gas_smell_is_p1_and_escalates(scopes) -> None:
    state = await run_case("I can smell gas near the kitchen pipe.", scopes["resident"])
    finding = state.finding("maintenance")
    assert finding is not None
    assert finding.structured["priority"] == "P1"
    assert finding.structured["safety_critical"] is True
    assert finding.structured["on_call_team"]
    assert state.risk_tier is RiskTier.ESCALATE_ONLY


async def test_uj8_ranked_followups_carry_reason_codes(scopes) -> None:
    state = await run_case("Who should I follow up with today?", scopes["sales_staff"])
    finding = state.finding("followup")
    assert finding is not None and finding.status == "ok"
    ranked = finding.structured["ranked"]
    assert ranked, "expected seeded leads due today"
    assert all(item["reason_codes"] for item in ranked[:3]), "ranking must be explainable"
    scores = [item["score"] for item in ranked]
    assert scores == sorted(scores, reverse=True)


async def test_every_case_writes_a_trace(scopes) -> None:
    from governance import audit

    state = await run_case("What is the status of Tower B?", scopes["manager"])
    trace = await audit.trace_for_case(state.case_id)
    agents = {row["agent"] for row in trace}
    assert {"masking", "classification", "router", "risk_engine", "gate"} <= agents


async def test_replay_reconstructs_the_decision(scopes) -> None:
    from governance import audit

    state = await run_case("What documents do I need for registration?", scopes["customer"])
    replay = await audit.replay(state.case_id)
    assert replay["found"] is True
    assert replay["steps"]
    assert replay["versions"]["prompts"], "a replay with no prompt version is not reproducible"


async def test_pii_is_masked_before_processing(scopes) -> None:
    state = await run_case(
        "My PAN is ABCDE1234F, please update my file.", scopes["customer"]
    )
    assert "ABCDE1234F" not in state.masked_input
    assert "PAN" in " ".join(state.metadata.get("masked_entities", []))


async def test_threading_groups_repeat_contact_within_24_hours(scopes) -> None:
    """FR-INT-6: a follow-up joins the same thread rather than starting a new one."""
    first = await run_case("What documents are pending for my registration?", scopes["customer"])
    second = await run_case("Any update on those documents?", scopes["customer"])
    assert second.thread_of in {first.case_id, first.thread_of or first.case_id}


async def test_attachments_are_carried_without_their_contents(scopes) -> None:
    """FR-INT-1 plus FR-DOC-5: the reference travels, the bytes never do."""
    state = await run_case(
        "Attaching my stamp duty receipt.",
        scopes["customer"],
        attachments=[
            {"filename": "receipt.pdf", "content_type": "application/pdf",
             "dms_doc_id": "DOC-TEST-1", "declared_type": "stamp_duty_receipt"}
        ],
    )
    attachments = state.metadata.get("attachments", [])
    assert attachments and attachments[0]["dms_doc_id"] == "DOC-TEST-1"
    assert "content" not in attachments[0], "document bytes must never enter case state"


async def test_documentation_produces_a_reminder_draft_not_a_sent_reminder(scopes) -> None:
    """FR-DOC-3."""
    state = await run_case(
        "What documents are still pending for my registration?", scopes["customer"]
    )
    finding = state.finding("documentation")
    assert finding is not None
    assert finding.structured["reminder_sent"] is False
    draft = finding.structured["reminder_draft"]
    assert draft and "still need" in draft


async def test_blocker_digest_is_ordered_and_internal(scopes) -> None:
    """FR-CTR-3 against the real connectors."""
    from governance import digest

    result = await digest.build("PRJ-AUR", scopes["manager"])
    assert result["internal_only"] is True
    assert result["project_id"] == "PRJ-AUR"
    severities = [e["severity"] for e in result["entries"]]
    ranks = [digest.SEVERITY_RANK.get(s, 0) for s in severities]
    assert ranks == sorted(ranks, reverse=True), "digest must be worst-first"
    assert result["headline"]
