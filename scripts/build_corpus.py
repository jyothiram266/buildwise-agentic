"""Build data/corpus/ from the seed fixtures and the policy YAML files.

Why generate rather than hand-write: the knowledge base states prices, unit
counts, SLA hours and warranty periods that the connectors also return as typed
fields. If the two are authored independently they drift, and every drift shows
up as a groundedness failure that looks like a model problem but is a data
problem. Generating both from one source removes that class of bug.

Hand-written prose (brochure copy, FAQ answers, procedural policy text) lives in
this file. Numbers come from data/seed/*.json and governance/policies/*.yaml.

Run: python scripts/build_corpus.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED = ROOT / "data" / "seed"
CORPUS = ROOT / "data" / "corpus"
POLICIES = ROOT / "governance" / "policies"
TODAY = date(2026, 8, 14)

ALL_ROLES = [
    "public_lead", "customer", "resident", "broker", "contractor",
    "sales_staff", "site_engineer", "legal_finance", "manager",
]
PUBLIC = ["public_lead", "customer", "resident", "broker", "sales_staff", "manager"]
INTERNAL = ["site_engineer", "legal_finance", "manager"]
CUSTOMER_FACING = ["customer", "resident", "sales_staff", "legal_finance", "manager"]


def load(name: str) -> list[dict]:
    return json.loads((SEED / name).read_text())


def rupees(amount: int) -> str:
    """Indian-format currency with a lakh/crore gloss, matching sales vocabulary."""
    if amount >= 10_000_000:
        gloss = f"{amount / 10_000_000:.2f} Cr"
    else:
        gloss = f"{amount / 100_000:.2f} L"
    s = str(amount)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"INR {s} ({gloss})"


def frontmatter(**kw) -> str:
    lines = ["---"]
    for key, value in kw.items():
        if value is None:
            continue
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(str(v) for v in value)}]")
        else:
            lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n\n"


written: list[Path] = []


def emit(collection: str, filename: str, head: str, body: str) -> None:
    path = CORPUS / collection / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + body.strip() + "\n")
    written.append(path)


# ---------------------------------------------------------------------------
# property_catalog — one brochure per project
# ---------------------------------------------------------------------------

BROCHURE_COPY = {
    "PRJ-AUR": (
        "Aurora Heights sits off Whitefield Main Road, within ten minutes of the ITPL "
        "corridor and walking distance of two international schools. The three towers are "
        "arranged around a central landscaped deck so that no living-room window faces "
        "another tower directly."
    ),
    "PRJ-PLM": (
        "Palm Meridian is a phased community in Gachibowli, positioned for the Financial "
        "District and the ORR interchange. Tower D is complete and occupied; Towers E and F "
        "remain under construction, so the community amenities are already operational for "
        "early residents."
    ),
    "PRJ-VTX": (
        "Vertex Commons offers full floor plates on Sarjapur Road for occupiers who want a "
        "single-tenant floor rather than a strata-divided office. Both blocks are ready for "
        "fit-out with services terminated at the floor."
    ),
    "PRJ-SRG": (
        "Serene Grove is a pre-launch villa cluster in Hinjewadi Phase 2. Layout approvals "
        "are in progress and no inventory has been released for sale. Interested buyers are "
        "recorded as expressions of interest only."
    ),
}
CONNECTIVITY = {
    "PRJ-AUR": [
        "Whitefield (Kadugodi) metro station — 3.4 km",
        "ITPL / EPIP Zone — 4.1 km",
        "Kempegowda International Airport — 42 km",
        "Two multi-speciality hospitals within 5 km",
    ],
    "PRJ-PLM": [
        "Gachibowli ORR interchange — 2.2 km",
        "Financial District — 3.8 km",
        "Rajiv Gandhi International Airport — 34 km",
        "University campus and IT parks within 5 km",
    ],
    "PRJ-VTX": [
        "Sarjapur Road arterial frontage",
        "Bellandur — 5.6 km",
        "Electronic City via Hosur Road — 14 km",
    ],
    "PRJ-SRG": [
        "Hinjewadi Phase 2 IT park — 2.9 km",
        "Mumbai–Pune Expressway access — 11 km",
        "Pune Airport — 28 km",
    ],
}


def build_catalog(projects, towers, units) -> None:
    by_project = defaultdict(list)
    for u in units:
        by_project[u["project_id"]].append(u)

    for p in projects:
        pid = p["project_id"]
        tws = [t for t in towers if t["project_id"] == pid]
        us = by_project[pid]
        configs = sorted({u["config"] for u in us})

        rows = ["| Configuration | Carpet area (sq ft) | Units in project | Currently available |",
                "|---|---|---|---|"]
        for cfg in configs:
            same = [u for u in us if u["config"] == cfg]
            lo = min(u["carpet_area"] for u in same)
            hi = max(u["carpet_area"] for u in same)
            avail = sum(1 for u in same if u["status"] == "available")
            rows.append(f"| {cfg} | {lo}–{hi} | {len(same)} | {avail} |")

        tower_rows = ["| Tower | Floors | Units | Status |", "|---|---|---|---|"]
        for t in tws:
            tower_rows.append(
                f"| {t['name']} | {t['floors']} | {t['units_total']} | {t['status'].replace('_', ' ')} |"
            )

        body = f"""# {p['name']} — Project Brochure

## Overview

{BROCHURE_COPY[pid]}

- **City:** {p['city']}
- **Locality:** {p['locality']}
- **Type:** {p['type']}
- **Project status:** {p['status'].replace('_', ' ')}
- **RERA registration:** {p['rera_id'] or 'not yet registered (pre-launch)'}
- **Planned possession:** {p['planned_possession'] or 'to be announced'}

## Configurations and inventory

{chr(10).join(rows)}

Availability changes continuously. The figures above are indicative; a live count
is served from the inventory system rather than from this document.

## Towers

{chr(10).join(tower_rows)}

## Amenities

{chr(10).join('- ' + a for a in p['amenities'])}

## Connectivity

{chr(10).join('- ' + c for c in CONNECTIVITY[pid])}

## Floor plans

Floor plates and unit plans are issued as PDF sets per configuration on request
through the sales desk. Plan sets are versioned against the sanctioned drawing
and superseded versions are withdrawn.

## What this document does not cover

Pricing is published separately in the current price list for the project, which
carries its own effective date. Discounts, waivers and negotiated rates are not
published in any document and are handled only by a sales executive.
"""
        head = frontmatter(
            source_id=f"BRO-{pid.split('-')[1]}",
            source_name=f"{p['name']} — Project Brochure",
            collection="property_catalog",
            effective_date=(TODAY - timedelta(days=40)).isoformat(),
            freshness_days=90,
            audience_scope=ALL_ROLES,
            project_id=pid,
        )
        emit("property_catalog", f"{pid.lower()}_brochure.md", head, body)


# ---------------------------------------------------------------------------
# pricing_sheets — generated from the same rate card as the inventory
# ---------------------------------------------------------------------------

SHEET_META = {
    # project: (source_id, days_old, note)
    "PRJ-AUR": ("PS-AUR-2026-07", 31, "stale"),  # freshness window is 7 days
    "PRJ-PLM": ("PS-PLM-2026-08", 4, "current"),
    "PRJ-VTX": ("PS-VTX-2026-06", 5, "current"),
    "PRJ-SRG": ("PS-SRG-PRELAUNCH", 6, "indicative"),
}


def build_pricing(projects, units) -> None:
    for p in projects:
        pid = p["project_id"]
        source_id, age, note = SHEET_META[pid]
        us = [u for u in units if u["project_id"] == pid]
        configs = sorted({u["config"] for u in us})
        eff = TODAY - timedelta(days=age)

        rows = [
            "| Configuration | Carpet area (sq ft) | Base price | All-inclusive price |",
            "|---|---|---|---|",
        ]
        for cfg in configs:
            same = sorted([u for u in us if u["config"] == cfg], key=lambda x: x["all_in_price"])
            lo, hi = same[0], same[-1]
            rows.append(
                f"| {cfg} | {lo['carpet_area']}–{hi['carpet_area']} | "
                f"{rupees(lo['base_price'])} onwards | {rupees(lo['all_in_price'])} – {rupees(hi['all_in_price'])} |"
            )

        prelaunch = pid == "PRJ-SRG"
        body = f"""# {p['name']} — Approved Price List

**Sheet reference:** {source_id}
**Effective date:** {eff.isoformat()}
**Status:** {'Indicative pre-launch range, not an offer' if prelaunch else 'Approved for customer quotation'}

## Price table

{chr(10).join(rows)}

All-inclusive price includes floor-rise, amenity charge and statutory charges as
applicable on the effective date. It excludes registration and stamp duty, which
are payable at actuals, and excludes GST where applicable.

## Rules attached to this sheet

1. Quote only the figures in this sheet, and only while it is the current sheet
   for the project. A superseded sheet must not be quoted.
2. No discount, waiver, cashback, or negotiated rate is published here or
   anywhere else. Any such request is handled by a sales executive with
   management authority.
3. A price quoted against a specific unit is valid only against a live
   availability check for that unit.
4. Floor-rise applies from the second floor upward at the rate loaded into the
   inventory system for each unit.

## Payment structure

The construction-linked payment plan is set out in the payment-milestone policy.
Deviation from that plan requires finance approval.
{'' if not prelaunch else chr(10) + '## Pre-launch caveat' + chr(10) * 2 + 'Serene Grove Villas has not launched. The range above is planning-stage guidance for internal use and expressions of interest. No unit can be blocked, held or booked against this sheet.'}
"""
        head = frontmatter(
            source_id=source_id,
            source_name=f"{p['name']} — Approved Price List ({eff.isoformat()})",
            collection="pricing_sheets",
            effective_date=eff.isoformat(),
            freshness_days=7,
            audience_scope=["public_lead", "customer", "broker", "sales_staff", "manager"],
            project_id=pid,
        )
        emit("pricing_sheets", f"{source_id.lower()}.md", head, body)


# ---------------------------------------------------------------------------
# doc_checklists — one document per booking stage
# ---------------------------------------------------------------------------



#: Rendered from governance/policies/document_checklists.yaml so the published
#: document and the requirement the agent computes cannot drift apart.
def _checklist_policy() -> dict:
    import yaml

    path = ROOT / "governance" / "policies" / "document_checklists.yaml"
    return yaml.safe_load(path.read_text())


def build_checklists() -> None:
    policy = _checklist_policy()
    stages = policy["stages"]
    for stage in policy["stage_order"]:
        spec = stages[stage]
        docs = [(d["type"], d["label"], d["note"]) for d in spec["documents"]]
        # The Type column carries the canonical identifier the DMS stores. It exists
        # so the documentation agent can compare submitted against required without
        # fuzzy-matching prose: "Stamp duty payment receipt" against
        # `stamp_duty_receipt` is exactly the kind of mapping that fails quietly.
        rows = ["| Document | Type | Required | Notes |", "|---|---|---|---|"]
        for doc_type, label, note in docs:
            rows.append(f"| {label} | `{doc_type}` | Yes | {note} |")
        body = f"""# {spec['title']} — Document Checklist

## Required documents

{chr(10).join(rows)}

## Where to submit

{spec['where_to_submit']}

## How completeness is assessed

A stage is complete when every document above is in `submitted` state and no
submitted document has passed its expiry date. An expired document is treated as
a gap, not as a submission: it must be replaced with a current copy.

## Scope of guidance

This checklist is procedural. It states what is required and where it goes. It
does not interpret any clause of the agreement, advise on stamp duty liability,
or comment on the legal effect of a document. Questions of that kind go to the
legal team.
"""
        head = frontmatter(
            source_id=f"CHK-{stage.upper()}",
            source_name=f"Document Checklist — {spec['title']}",
            collection="doc_checklists",
            effective_date=(TODAY - timedelta(days=95)).isoformat(),
            freshness_days=180,
            audience_scope=CUSTOMER_FACING,
        )
        emit("doc_checklists", f"checklist_{stage}.md", head, body)


# ---------------------------------------------------------------------------
# policies — rendered from YAML so code and document cannot diverge
# ---------------------------------------------------------------------------


def build_policies() -> None:
    sev = yaml.safe_load((POLICIES / "severity_matrix.yaml").read_text())
    esc = yaml.safe_load((POLICIES / "escalation_matrix.yaml").read_text())
    war = yaml.safe_load((POLICIES / "warranty_policy.yaml").read_text())

    # --- maintenance SLA + severity matrix ---
    sla_rows = ["| Priority | First response | Resolution SLA |", "|---|---|---|"]
    for pri in ("P1", "P2", "P3", "P4"):
        sla_rows.append(f"| {pri} | {sev['response_hours'][pri]} h | {sev['sla_hours'][pri]} h |")

    team_rows = ["| Category | Owning team | Default priority |", "|---|---|---|"]
    for cat, team in sev["teams"].items():
        team_rows.append(f"| {cat} | {team} | {sev['category_defaults'][cat]} |")

    safety_rows = ["| Hazard class | Description | On-call path |", "|---|---|---|"]
    for _key, val in sev["safety_critical"].items():
        safety_rows.append(f"| {val['label']} | Forced P1, model confidence not consulted | {val['on_call']} |")

    rule_rows = ["| Rule | Priority | Applies to | Condition |", "|---|---|---|---|"]
    for r in sev["rules"]:
        cats = ", ".join(r["categories"])
        rule_rows.append(f"| {r['id']} | {r['priority']} | {cats} | {r['reason']} |")

    body = f"""# Maintenance SLA and Severity Matrix

**Policy:** {sev['policy_id']} · version {sev['version']} · effective {sev['effective_date']}

## Service levels

{chr(10).join(sla_rows)}

The resolution clock starts when the ticket is created and runs on calendar hours
for P1 and P2, and on business hours for P3 and P4.

## Category ownership

{chr(10).join(team_rows)}

## Safety-critical classes

These bypass normal routing. The ticket is raised at P1 and the human on-call
path is notified immediately, regardless of how the request was worded or how
confident the classifier was.

{chr(10).join(safety_rows)}

## Priority assignment rules

Rules are evaluated in order and the first match decides the priority. If no rule
matches, the category default applies. Priority is assigned in code from this
table, not by a language model.

{chr(10).join(rule_rows)}

## Escalation on breach

A ticket that crosses its resolution SLA is escalated to the facility manager and
appears on the leadership dashboard in the breached bucket. Breach does not close
the ticket or reset the clock.
"""
    emit(
        "policies",
        "maintenance_sla_policy.md",
        frontmatter(
            source_id=sev["policy_id"],
            source_name="Maintenance SLA and Severity Matrix",
            collection="policies",
            effective_date=sev["effective_date"],
            freshness_days=365,
            audience_scope=ALL_ROLES,
        ),
        body,
    )

    # --- warranty policy ---
    rows = ["| Component | Coverage from possession | Scope |", "|---|---|---|"]
    for _key, val in war["components"].items():
        rows.append(f"| {val['label']} | {val['months']} months | Workmanship and material defects |")
    body = f"""# Warranty Policy

**Policy:** {war['policy_id']} · version {war['version']} · effective {war['effective_date']}

## Coverage periods

Coverage runs from the date of possession recorded against the booking.

{chr(10).join(rows)}

{war['statutory_note']}

## Exclusions

{chr(10).join('- ' + e for e in war['exclusions'])}

## How a claim is assessed

1. The resident raises a ticket describing the defect.
2. Coverage is computed from the possession date on the booking and the component
   period above. The result is an **indication**, not a decision.
3. A technician inspects and confirms whether the cause falls inside coverage.
4. Confirmation of cover is issued by the customer relations team, in writing.

No automated response confirms warranty cover. The most an automated response
says is that a component appears to fall inside or outside the period, pending
inspection.
"""
    emit(
        "policies",
        "warranty_policy.md",
        frontmatter(
            source_id=war["policy_id"],
            source_name="Warranty Policy",
            collection="policies",
            effective_date=war["effective_date"],
            freshness_days=365,
            audience_scope=ALL_ROLES,
        ),
        body,
    )

    # --- escalation routing matrix ---
    rows = ["| Escalation type | Owner team | Response SLA | Minimum tier |", "|---|---|---|---|"]
    for _key, val in esc["types"].items():
        rows.append(
            f"| {val['label']} | {val['owner_team']} | {val['sla_hours']} h | Tier {val['tier']} |"
        )
    body = f"""# Escalation Routing Matrix

**Policy:** {esc['policy_id']} · version {esc['version']} · effective {esc['effective_date']}

## Routing table

{chr(10).join(rows)}

## Rules

1. Where more than one type matches, the shortest SLA and the highest tier apply.
2. Tier 3 means no substantive automated answer is sent. The customer receives an
   acknowledgement, a named owning team and a response commitment.
3. Uncertainty is itself a trigger. Low pipeline confidence, conflicting approved
   sources and missing system-of-record data each raise an escalation on their
   own, independent of the topic.
4. No automated path resolves or closes an escalation. Closure is a human action
   recorded against a named person.
5. The SLA clock starts when the escalation record is created, not when a human
   opens it.
"""
    emit(
        "policies",
        "escalation_routing_matrix.md",
        frontmatter(
            source_id=esc["policy_id"],
            source_name="Escalation Routing Matrix",
            collection="policies",
            effective_date=esc["effective_date"],
            freshness_days=365,
            audience_scope=ALL_ROLES,
        ),
        body,
    )

    # --- payment milestone policy (hand written, structure mirrors the fixtures) ---
    body = """# Payment Milestone Policy

**Policy:** POL-PAY-MS · version 1.4.0 · effective 2026-03-01

## Construction-linked plan

| Milestone | Share of consideration | Trigger |
|---|---|---|
| On booking | 10% | Booking form accepted |
| Foundation complete | 15% | Foundation and raft certified complete |
| Structure 50% | 20% | Half the slabs cast for the tower |
| Structure complete | 20% | Final slab cast |
| Brickwork & MEP | 15% | Blockwork and MEP rough-in certified |
| Finishing | 10% | Internal finishing certified |
| On possession | 10% | Possession notice issued |

Amounts are computed on the all-inclusive consideration recorded on the booking.
Statutory charges are billed at actuals separately.

## Demand notes

A demand note is raised when the milestone is certified by the project team. It
states the amount, the due date and the milestone that triggered it. Payment is
due within 21 days of the demand note date.

## Delay interest

Interest accrues on an overdue amount from the day after the due date at the rate
stated in the agreement. Interest is computed by the finance system. No automated
response quotes, computes, waives or reduces interest.

## What is never automated

- No refund, adjustment, waiver or write-off is initiated by any automated path.
- No payment is recorded, reversed or reallocated by any automated path. The
  payments integration is read-only by design.
- A disputed demand note is escalated to legal and finance, not answered.

## What a customer can be told automatically

The schedule, the amount and due date of each milestone, whether a milestone is
paid, due or overdue, and the receipt reference for a paid milestone. These are
read from the payments system as typed fields and quoted exactly.
"""
    emit(
        "policies",
        "payment_milestone_policy.md",
        frontmatter(
            source_id="POL-PAY-MS",
            source_name="Payment Milestone Policy",
            collection="policies",
            effective_date="2026-03-01",
            freshness_days=365,
            audience_scope=["customer", "resident", "sales_staff", "legal_finance", "manager"],
        ),
        body,
    )

    # --- disclosure policy: what may and may not be said to whom ---
    body = """# Customer Disclosure Policy

**Policy:** POL-DISC · version 1.1.0 · effective 2026-05-01

## Never disclosed to an external audience

- Contractor commercial disputes, retention claims and vendor payment matters.
- Internal cost figures, budget variance and contractor rates.
- Safety incident detail, including near-miss reports and site audit findings.
- Any possession date that has not been approved and recorded as the current
  date for the tower. An internally discussed date is not a date.
- Another customer's booking, payment or document status, in any form.

## Disclosed with care

- Slippage against the original plan may be described in factual terms once the
  revised date is approved. Until then, the position is that the date is under
  review and a specific new date is not available.
- Delay causes may be described in general categories (approvals, material
  supply, manpower, weather) without naming a vendor or a commercial dispute.

## Always disclosed

- The source and effective date of any figure quoted.
- Whether the information is older than its freshness window.
- The fact that a case has been escalated, the owning team, and the response
  commitment.

## Tone by audience

| Audience | Disclosure level |
|---|---|
| Prospective buyer | Published catalogue, current price list, generic process |
| Customer | Own booking, own payments, own documents, customer-safe project view |
| Resident | Own unit, own tickets, community notices |
| Broker | Availability status and brochure assets, own commission records |
| Contractor | Own work package and submissions; no commitments of any kind |
| Internal | Full technical detail appropriate to the role |
"""
    emit(
        "policies",
        "customer_disclosure_policy.md",
        frontmatter(
            source_id="POL-DISC",
            source_name="Customer Disclosure Policy",
            collection="policies",
            effective_date="2026-05-01",
            freshness_days=365,
            audience_scope=ALL_ROLES,
        ),
        body,
    )


# ---------------------------------------------------------------------------
# project_reports — internal-scope digests
# ---------------------------------------------------------------------------


def build_project_reports(towers, milestones, blockers) -> None:
    by_tower = defaultdict(list)
    for m in milestones:
        by_tower[m["tower_id"]].append(m)

    for project_id, label in (("PRJ-AUR", "Aurora Heights"), ("PRJ-PLM", "Palm Meridian")):
        tws = [t for t in towers if t["project_id"] == project_id]
        rows = ["| Tower | Milestone | Planned | Actual | Status | % complete |", "|---|---|---|---|---|---|"]
        for t in tws:
            for m in sorted(by_tower[t["tower_id"]], key=lambda x: x["seq"]):
                rows.append(
                    f"| {t['name']} | {m['name']} | {m['planned_date']} | {m['actual_date'] or '—'} "
                    f"| {m['status']} | {m['pct_complete']:.0f} |"
                )
        blk = [b for b in blockers if b["project_id"] == project_id and not b["resolved_on"]]
        blk_rows = ["| Blocker | Category | Severity | Raised | Impacted milestones |", "|---|---|---|---|---|"]
        for b in blk:
            blk_rows.append(
                f"| {b['blocker_id']} | {b['category']} | {b['severity']} | {b['raised_on']} "
                f"| {', '.join(b['impacted_milestones'])} |"
            )
        rev = [t for t in tws if t["revised_possession"]]
        rev_rows = ["| Tower | Original | Revised | Approved for disclosure |", "|---|---|---|---|"]
        for t in rev:
            rev_rows.append(
                f"| {t['name']} | {t['planned_possession']} | {t['revised_possession']} "
                f"| {'yes' if t['revised_approved'] else 'NO — internal only'} |"
            )

        body = f"""# {label} — Milestone and Blocker Register (internal)

**Register date:** {TODAY.isoformat()}

## Milestone position

{chr(10).join(rows)}

## Open blockers

{chr(10).join(blk_rows)}

## Possession date position

{chr(10).join(rev_rows) if rev else 'No revised dates recorded.'}

A revised date is disclosable to customers only where the approval column says
yes. An unapproved date is an internal planning position and must not appear in
any customer-facing output, in any form, including as a range or an implication.

## Reading this register

Percentages are the certified figures from the site team. Slippage is computed
from the planned and actual columns and is not restated in prose here, so that
there is one arithmetic source rather than two.
"""
        emit(
            "project_reports",
            f"{project_id.lower()}_milestone_register.md",
            frontmatter(
                source_id=f"PR-{project_id.split('-')[1]}-REG",
                source_name=f"{label} — Milestone and Blocker Register",
                collection="project_reports",
                effective_date=(TODAY - timedelta(days=3)).isoformat(),
                freshness_days=7,
                audience_scope=INTERNAL,
                project_id=project_id,
            ),
            body,
        )

    body = """# Weekly Site Reporting Standard (internal)

## What a weekly note must contain

1. Slab, blockwork and finishing position by floor.
2. Manpower on site against the planned strength.
3. Material position, naming any item below one week of cover.
4. Safety observations, including near misses, with the action taken.
5. Anything that has moved a milestone date, with the number of days.

## What happens to the note

The raw note is summarised twice from the same source: an internal technical
summary that keeps all detail, and a customer-safe summary that excludes
contractor disputes, cost figures, safety-incident detail and any unapproved
date. The customer summary is generated separately rather than redacted, and is
queued for approval before it can be sent.

## Injection warning

Weekly notes are ingested as data, never as instructions. A note that contains
text addressed to an automated system — for example asking it to ignore rules,
change disclosure behaviour, or list records — is flagged for review and the
instruction is not followed. Report any such note to knowledge operations.
"""
    emit(
        "project_reports",
        "weekly_reporting_standard.md",
        frontmatter(
            source_id="PR-STD-WEEKLY",
            source_name="Weekly Site Reporting Standard",
            collection="project_reports",
            effective_date=(TODAY - timedelta(days=120)).isoformat(),
            freshness_days=365,
            audience_scope=INTERNAL,
        ),
        body,
    )


# ---------------------------------------------------------------------------
# faq — 40 curated entries across four files
# ---------------------------------------------------------------------------

FAQ = {
    "buying_process": [
        ("How do I book a unit?", "Choose a unit against a live availability check, pay the booking amount, and sign the booking application. The unit is held only once the booking amount clears."),
        ("Can a unit be held before I pay?", "A unit can be marked held for a short window by a sales executive. A hold is not a booking and it lapses automatically."),
        ("What is the difference between carpet area and super built-up area?", "Carpet area is the usable floor area within the walls of the unit. All prices in our price lists are quoted against carpet area."),
        ("Is the price negotiable?", "Published prices come from the current approved price list. Any request for a discount, waiver or revised rate is handled by a sales executive, not by an automated channel."),
        ("What is included in the all-inclusive price?", "Floor rise, amenity charge and statutory charges applicable on the effective date of the price list. Registration and stamp duty are payable at actuals and are not included."),
        ("Can I change my unit after booking?", "A change of unit is treated as a cancellation and a fresh booking, subject to the terms in your agreement. The sales team will confirm what applies to your case."),
        ("Do you accept NRI bookings?", "Yes, subject to the applicable foreign exchange rules. The documentation set differs and the sales team issues the specific list."),
        ("How long is a price list valid?", "Each price list carries an effective date. When a new list is issued the earlier one is withdrawn and must not be quoted."),
        ("Can I visit the site before booking?", "Yes. Site visits are arranged through the sales desk and are the usual next step after an initial enquiry."),
        ("What is a pre-launch project?", "A project where approvals are still in progress and no inventory has been released for sale. Interest is recorded as an expression of interest only."),
    ],
    "payments_and_documents": [
        ("How is my payment schedule decided?", "By the construction-linked plan in the payment milestone policy, applied to the consideration on your booking."),
        ("When is a demand note raised?", "When the project team certifies the milestone. Payment is due within 21 days of the demand note date."),
        ("What happens if I pay late?", "Interest accrues from the day after the due date at the rate in your agreement. The finance system computes it; no automated channel quotes or adjusts it."),
        ("Where do I see what I have paid?", "The payment schedule with paid, due and overdue status is read directly from the payments system and can be shown against your booking."),
        ("Can a payment be waived or refunded through this channel?", "No. The payments integration is read-only. Any refund, waiver or adjustment request goes to the legal and finance team."),
        ("What documents do I need for registration?", "The stage 3 checklist lists them. Typically the agreement acknowledgement, stamp duty receipt, witness identity proof, and a bank sanction letter for loan-funded bookings."),
        ("My document has expired. Is it still valid?", "No. An expired document counts as a gap and must be replaced with a current copy before the stage can be treated as complete."),
        ("Who interprets a clause in my agreement?", "The legal team. Automated guidance is limited to what is required and where to submit it, and does not extend to what a clause means."),
        ("How do I submit documents?", "Through the customer portal for most documents. Registration documents are handled at the registration desk and originals are collected at the sub-registrar office."),
        ("Will you remind me about pending documents?", "A reminder can be drafted for you, but it is sent only after a human or a scheduled policy approves it."),
    ],
    "construction_and_possession": [
        ("How do I check construction progress?", "Milestone status per tower, with percentage completion and the date of the last certified update, is available against your booking."),
        ("Why does the progress date differ from what I saw last month?", "Milestone dates are certified by the site team as work completes. Where a date has moved, the register records the planned and the actual date separately."),
        ("Will you tell me a new possession date if the old one moves?", "Only if a revised date has been approved and recorded. An internally discussed date is not shared, because it is not a commitment."),
        ("What causes construction delays?", "Commonly approvals, material supply, manpower availability and weather. Specific commercial matters between the developer and a vendor are not discussed with customers."),
        ("How is slippage measured?", "As the difference in days between the planned and the actual date of each milestone. The figure is computed from the register, not estimated."),
        ("Can I visit my unit during construction?", "Site visits during construction are arranged with the site team and require safety clearance and escort."),
        ("What happens at handover?", "A joint snag inspection, a signed handover checklist, the possession letter after final payment clears, and the maintenance deposit receipt."),
        ("How long is the snag rectification window?", "Snags identified at the joint inspection are rectified before the possession letter is issued. Defects found later fall under the warranty policy."),
        ("Who do I contact about a delay?", "A possession-date or delay concern is routed to customer relations with a response commitment; it is not answered automatically."),
        ("Is the RERA registration number available?", "Yes, it is published in the project brochure for every registered project."),
    ],
    "living_and_maintenance": [
        ("How do I raise a maintenance request?", "Describe the issue for your unit. It is categorised, prioritised against the severity matrix, and a ticket is created with an SLA window."),
        ("How quickly will someone respond?", "P1 within 1 hour and resolved within 4, P2 within 4 hours and resolved within 24, P3 within 12 hours and resolved within 72, P4 within a day and resolved within a week."),
        ("What counts as an emergency?", "A gas leak, a live electrical hazard, a suspected structural crack, or a person trapped in a lift. These go straight to the on-call path."),
        ("Is my issue covered under warranty?", "Coverage is computed from your possession date and the component period in the warranty policy. The answer is an indication; cover is confirmed after inspection."),
        ("How long is plumbing covered?", "Concealed plumbing and fittings are covered for 12 months from possession, subject to the exclusions in the warranty policy."),
        ("How long is the structure covered?", "Structural elements and waterproofing are covered for 60 months from handover."),
        ("What is not covered by warranty?", "Damage from resident alterations, normal wear and tear, consumables, force majeure damage, and anything reported after the coverage period."),
        ("My ticket has crossed its SLA. What happens?", "It is escalated to the facility manager and appears in the breached bucket on the operations dashboard. The ticket stays open until the work is done."),
        ("Who maintains the common areas?", "The facility team, with the resident association once it is formed. Housekeeping, security and vertical transport each have an owning team."),
        ("Can I get someone else's ticket status?", "No. Access is limited to your own unit and your own tickets."),
    ],
}
FAQ_TITLES = {
    "buying_process": "Buying Process",
    "payments_and_documents": "Payments and Documents",
    "construction_and_possession": "Construction and Possession",
    "living_and_maintenance": "Living and Maintenance",
}


def build_faq() -> None:
    total = 0
    for key, entries in FAQ.items():
        total += len(entries)
        sections = []
        for q, a in entries:
            sections.append(f"## {q}\n\n{a}")
        body = f"# Frequently Asked Questions — {FAQ_TITLES[key]}\n\n" + "\n\n".join(sections)
        emit(
            "faq",
            f"faq_{key}.md",
            frontmatter(
                source_id=f"FAQ-{key.upper()}",
                source_name=f"FAQ — {FAQ_TITLES[key]}",
                collection="faq",
                effective_date=(TODAY - timedelta(days=25)).isoformat(),
                freshness_days=90,
                audience_scope=ALL_ROLES,
            ),
            body,
        )
    if total != 40:
        raise SystemExit(f"FAQ must hold exactly 40 entries, found {total}")


def main() -> int:
    projects = load("projects.json")
    towers = load("towers.json")
    units = load("units.json")
    milestones = load("milestones.json")
    blockers = load("blockers.json")

    build_catalog(projects, towers, units)
    build_pricing(projects, units)
    build_checklists()
    build_policies()
    build_project_reports(towers, milestones, blockers)
    build_faq()

    print(f"wrote {len(written)} corpus documents")
    for p in sorted(written):
        print(f"  {p.relative_to(ROOT)}")
    stale = TODAY - timedelta(days=SHEET_META['PRJ-AUR'][1])
    print(f"\nAurora price list effective {stale} with a 7-day window: deliberately stale.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
