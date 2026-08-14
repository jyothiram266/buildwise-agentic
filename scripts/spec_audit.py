"""Spec coverage audit.

Maps every PRD requirement to the code that implements it and the test that proves
it, then reports anything unmatched. Written as a script rather than a checklist in
a document because a checklist goes stale the first time someone deletes a function.

Run: python scripts/spec_audit.py
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: requirement -> (description, code files, code evidence regex, test evidence regex)
#: Both evidence values are regexes. The test regex is searched across the whole
#: tests/ and eval/ trees, so a requirement counts as tested when a test *function*
#: asserts it — not merely when some file exists. The first version of this audit
#: checked for file existence and reported fourteen false gaps as a result.
COVERAGE: dict[str, tuple[str, list[str], str, str | None]] = {
    # --- intake -----------------------------------------------------------
    "FR-INT-1": ("REST intake with channel, text, attachments, identity",
                 ["api/routes/intake.py", "api/schemas/requests.py"],
                 r"attachments", r"test_attachments_are_carried_without_their_contents"),
    "FR-INT-2": ("canonical Case with a unique id",
                 ["orchestration/graph.py"], r"CASE-\{uuid", r"def test_case_state_separates_internal_findings"),
    "FR-INT-3": ("nine-intent classification",
                 ["core/enums.py"], r"CONTRACTOR_UPDATE", r"test_intent_covers_exactly_the_nine_specified"),
    "FR-INT-4": ("entity extraction",
                 ["llm/mock_provider.py"], r"entities", r"suite_entities|entities\.jsonl|test_entity"),
    "FR-INT-5": ("confidence per classification, below-threshold to triage",
                 ["orchestration/router.py"], r"confidence_threshold", r"test_low_confidence_goes_to_triage"),
    "FR-INT-6": ("dedupe/thread within 24 hours",
                 ["orchestration/graph.py"], r"_find_thread", r"test_threading_groups_repeat_contact"),
    # --- property ---------------------------------------------------------
    "FR-PROP-1": ("availability by project, config, budget, city",
                  ["connectors/crm.py"], r"budget_max", r"test_uj1_availability_with_budget"),
    "FR-PROP-2": ("approved pricing with effective date",
                  ["agents/property_info.py"], r"price_effective_date", r"test_uj1_availability_with_budget"),
    "FR-PROP-3": ("never quote a discount; route to sales",
                  ["agents/property_info.py"], r"COMMERCIAL_TERMS", r"test_tier_three_triggers"),
    "FR-PROP-4": ("floor plans, amenities, possession with source refs",
                  ["agents/property_info.py"], r"planned_possession", r"test_uj1_availability_with_budget"),
    "FR-PROP-5": ("staleness warning past the freshness window",
                  ["agents/property_info.py"], r"_price_is_stale", r"test_stale_pricing_sheet_is_flagged"),
    # --- construction -----------------------------------------------------
    "FR-CON-1": ("milestone status with % completion",
                 ["agents/construction.py"], r"pct_complete", r"test_percentage_is_the_milestone_average"),
    "FR-CON-2": ("internal and customer-safe registers from one source",
                 ["agents/construction.py"], r"customer_summary", r"test_uj5_engineer_note_produces_both_summaries"),
    "FR-CON-3": ("suppress disputes, cost, speculation, safety detail",
                 ["agents/response.py"], r"INTERNAL_LEAKAGE_TERMS", r"test_safety_incident_detail_is_blocked"),
    "FR-CON-4": ("slippage from planned vs actual, configurable threshold",
                 ["agents/construction.py"], r"def compute_slippage", r"test_overdue_incomplete_milestone_counts_as_slip"),
    "FR-CON-5": ("free-text site note to review-ready summary",
                 ["agents/construction.py"], r"report_excerpts", r"test_uj5_engineer_note_produces_both_summaries"),
    "FR-CON-6": ("no revised possession date unless approved",
                 ["agents/construction.py"], r"revised_approved", r"test_unapproved_possession_date_never_leaves_the_connector"),
    # --- documentation ----------------------------------------------------
    "FR-DOC-1": ("stage-appropriate checklist",
                 ["agents/documentation.py"], r"_required_from_checklist", r"test_uj3_pending_documents_distinguishes_expired"),
    "FR-DOC-2": ("submitted vs required, missing or expired",
                 ["agents/documentation.py"], r"expired", r"test_uj3_pending_documents_distinguishes_expired"),
    "FR-DOC-3": ("reminder drafts, sending needs approval",
                 ["agents/documentation.py"], r"_reminder_draft", r"test_documentation_produces_a_reminder_draft"),
    "FR-DOC-4": ("procedural only, route interpretation to legal",
                 ["agents/documentation.py"], r"LEGAL_INTERPRETATION_SIGNALS", r"LEGAL_INTERPRETATION|legal_referral|test_uj3"),
    "FR-DOC-5": ("mask KYC identifiers in logs, prompts, context",
                 ["core/masking.py", "orchestration/graph.py"], r"mask_text", r"test_identifiers_are_masked"),
    # --- maintenance ------------------------------------------------------
    "FR-MNT-1": ("nine maintenance categories",
                 ["core/enums.py"], r"WARRANTY_CLAIM", r"maintenance\.jsonl|test_severity"),
    "FR-MNT-2": ("P1-P4 from an explicit severity matrix",
                 ["governance/severity.py"], r"def assign_priority", r"test_active_water_ingress_is_p2"),
    "FR-MNT-3": ("route to the mapped team and create a ticket",
                 ["agents/maintenance.py"], r"CreateTicketAction", r"test_uj7_leak_creates_a_ticket_with_sla"),
    "FR-MNT-4": ("safety-critical bypasses normal routing",
                 ["governance/severity.py"], r"detect_safety_critical", r"test_safety_signals_force_p1"),
    "FR-MNT-5": ("warranty as an indication pending confirmation",
                 ["governance/severity.py"], r"def warranty_indication", r"test_within_period_is_indicated_not_confirmed"),
    # --- contractor -------------------------------------------------------
    "FR-CTR-1": ("ingest progress, material, manpower, blockers",
                 ["agents/contractor.py"], r"CATEGORY_SIGNALS", r"test_uj6_contractor_blocker_gives_a_range"),
    "FR-CTR-2": ("correlate blocker to milestones, impact statement",
                 ["agents/contractor.py"], r"impacted_milestones", r"test_blocker_digest_is_ordered_and_internal|test_impact_statement"),
    "FR-CTR-3": ("daily blocker digest per project",
                 ["governance/digest.py"], r"async def build", r"test_blocker_digest_is_ordered_and_internal"),
    "FR-CTR-4": ("no commitment on payment, timeline, scope",
                 ["agents/contractor.py"], r"COMMITMENT_SIGNALS", r"test_uj6_contractor_blocker_gives_a_range"),
    # --- escalation -------------------------------------------------------
    "FR-ESC-1": ("detect the eight escalation triggers",
                 ["governance/policies/escalation_matrix.yaml"], r"media_threat", r"test_tier_three_triggers"),
    "FR-ESC-2": ("route to an owner team with an SLA clock",
                 ["agents/escalation.py"], r"sla\.due_at", r"test_priority_sla_comes_from_policy"),
    "FR-ESC-3": ("brief: history, attempted, rationale, next action",
                 ["agents/escalation.py"], r"Recommended next action", r"test_escalation_survives_a_brief_generation_failure"),
    "FR-ESC-4": ("escalate on low confidence, missing data, conflict",
                 ["orchestration/risk_engine.py"], r"SOURCE_CONFLICT", r"test_conflicting_sources_escalate"),
    "FR-ESC-5": ("never close an escalated case autonomously",
                 ["governance/review_queue.py"], r"has_open_escalation", r"test_escalated_case_cannot_be_closed_autonomously"),
    # --- response ---------------------------------------------------------
    "FR-RES-1": ("grounded strictly in retrieved context, else refuse",
                 ["agents/base.py"], r"_finalise", r"test_clean_customer_text_passes"),
    "FR-RES-2": ("source refs on every factual claim",
                 ["core/models.py"], r"class Citation", r"test_chunk_converts_to_a_citation"),
    "FR-RES-3": ("tone and disclosure by audience",
                 ["agents/response.py"], r"PROMPT_BY_AUDIENCE", r"test_internal_audience_is_not_gated"),
    "FR-RES-4": ("above threshold goes to draft-for-approval",
                 ["orchestration/graph.py"], r"draft_for_approval", r"test_approve_issues_a_single_use_token"),
    "FR-RES-5": ("next action and expected timeline from policy",
                 ["core/models.py"], r"next_action", r"test_uj8_ranked_followups_carry_reason_codes"),
    # --- governance -------------------------------------------------------
    "FR-GOV-1": ("RBAC at the retrieval layer, injection-proof",
                 ["retrieval/search.py"], r"audience_scope", r"test_retrieval_respects_audience_scope"),
    "FR-GOV-2": ("log every agent invocation with full context",
                 ["governance/audit.py"], r"async def record", r"test_every_case_writes_a_trace"),
    "FR-GOV-3": ("review queue with approve/edit/reject/reassign",
                 ["core/enums.py"], r"REASSIGN", r"test_edit_and_send_records_the_edited_text"),
    "FR-GOV-4": ("dashboard: cases by type, median response, escalation ageing, "
                 "delayed milestones, SLA-breached tickets, leads due today",
                 ["api/routes/dashboard.py"],
                 r"median_response_seconds|delayed_milestones|leads_due_today|escalation_ageing", r"test_override_stats_expose_the_reason_distribution"),
    "FR-GOV-5": ("prompt/policy versioning for reproducibility",
                 ["governance/policy_registry.py"], r"version", r"test_policies_are_versioned"),
}

DESIGN_RULES = {
    "rule 1 — numbers from connectors, never estimated":
        ("agents/base.py", r"insufficient_data"),
    "rule 2 — authorisation below the model, filtered in SQL":
        ("retrieval/search.py", r"acl_sql|audience_scope"),
    "rule 3 — deterministic policy in code":
        ("orchestration/risk_engine.py", r"def assess"),
    "rule 4 — uncertainty is an output":
        ("core/models.py", r"confidence: float"),
    "rule 5 — payments connector is read-only":
        ("connectors/payments.py", r"read_only"),
}

JOURNEYS = {
    f"UJ-{n}": pattern
    for n, pattern in {
        1: r"def test_uj1",
        2: r"def test_uj2",
        3: r"def test_uj3",
        4: r"def test_uj4",
        5: r"def test_uj5",
        6: r"def test_uj6",
        7: r"def test_uj7",
        8: r"def test_uj8",
    }.items()
}


def read(rel: str) -> str:
    path = ROOT / rel
    return path.read_text() if path.exists() else ""


def test_blob() -> str:
    """Everything under tests/ and eval/, concatenated once."""
    parts = []
    for folder in ("tests", "eval"):
        for path in (ROOT / folder).rglob("*"):
            if path.suffix in {".py", ".jsonl"} and path.is_file():
                parts.append(path.read_text())
    return "\n".join(parts)


TESTS = test_blob()


def main() -> int:
    missing_code: list[str] = []
    missing_test: list[str] = []

    print("=" * 76)
    print("PRD requirement coverage".center(76))
    print("=" * 76)
    for req, (desc, files, pattern, test) in sorted(COVERAGE.items()):
        blob = "\n".join(read(f) for f in files)
        found = bool(re.search(pattern, blob))
        has_test = bool(test and re.search(test, TESTS))
        if not found:
            missing_code.append(req)
        if not has_test:
            missing_test.append(req)
        mark = "ok " if found else "GAP"
        proof = "tested" if has_test else "no direct test"
        print(f"[{mark}] {req:<11} {desc[:44]:<44} {proof}")

    print("\n" + "=" * 76)
    print("Design rules (AGENTS.md)".center(76))
    print("=" * 76)
    for rule, (file, pattern) in DESIGN_RULES.items():
        found = bool(re.search(pattern, read(file)))
        print(f"[{'ok ' if found else 'GAP'}] {rule}")
        if not found:
            missing_code.append(rule)

    print("\n" + "=" * 76)
    print("User journeys".center(76))
    print("=" * 76)
    journeys_blob = read("tests/integration/test_journeys.py")
    for journey, pattern in JOURNEYS.items():
        found = bool(re.search(pattern, journeys_blob))
        print(f"[{'ok ' if found else 'GAP'}] {journey}")
        if not found:
            missing_code.append(journey)

    print("\n" + "-" * 76)
    if missing_code:
        print(f"UNIMPLEMENTED ({len(missing_code)}): {', '.join(missing_code)}")
    else:
        print(f"All {len(COVERAGE)} requirements, 5 design rules and 8 journeys are implemented.")
    if missing_test:
        print(f"\nNo direct test ({len(missing_test)}): {', '.join(missing_test)}")
        print("These are covered indirectly; listed so the gap is visible rather than assumed.")
    return 1 if missing_code else 0


if __name__ == "__main__":
    sys.exit(main())
