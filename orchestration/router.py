"""Routing. A table, not a decision.

Design rule #3: the model classifies, code routes. The mapping below is the whole
policy — readable in one screen, testable without a network call, and impossible to
prompt-inject, because nothing an actor writes reaches this logic except through an
already-validated `Intent` enum.

Low classification confidence does not get routed to a specialist at all. Running
three agents on a guess produces three confident-looking findings about the wrong
question, which is more expensive to unwind than a triage handoff.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.enums import Intent, Role
from core.models import Classification
from governance.severity import detect_safety_critical

#: Intent -> ordered agent names. Order is presentation order in the response; the
#: graph runs them concurrently.
ROUTES: dict[Intent, list[str]] = {
    Intent.SALES_INQUIRY: ["property_info"],
    Intent.BOOKING: ["documentation", "payments"],
    Intent.DOCUMENTATION: ["documentation"],
    Intent.PAYMENT: ["payments"],
    Intent.CONSTRUCTION_STATUS: ["construction"],
    Intent.MAINTENANCE: ["maintenance"],
    Intent.CONTRACTOR_UPDATE: ["contractor"],
    Intent.COMPLAINT_ESCALATION: [],  # handled by the risk engine and escalation agent
    Intent.OTHER: [],
}

#: Follow-up list requests arrive as SALES_INQUIRY from a sales user. Detected on
#: phrasing here rather than as a tenth intent, because it is a different *view* of
#: the same intent, and adding intents to satisfy one report degrades classification.
FOLLOWUP_PHRASES = (
    "follow up", "follow-up", "followup", "who should i call", "my leads", "priority list",
    "action list", "today's list", "todays list", "pipeline", "next actions", "chase",
)

SALES_ROLES = {Role.SALES_STAFF, Role.MANAGER}


@dataclass
class RoutingPlan:
    agents: list[str] = field(default_factory=list)
    triage: bool = False
    reason: str = ""

    @property
    def runs_specialists(self) -> bool:
        return bool(self.agents) and not self.triage


def plan(
    classification: Classification | None,
    role: Role,
    text: str,
    confidence_threshold: float = 0.70,
) -> RoutingPlan:
    """Decide which specialists run. Pure function; no I/O, no model.

    Deterministic overrides are evaluated **before** the confidence gate. That order
    is the whole point and it was wrong in the first version: a resident writing
    "I can smell gas near the kitchen pipe" classified at 0.35 confidence, fell into
    triage, and the maintenance agent — which holds the hazard rules — never ran. No
    ticket, no P1, no on-call page. The severity matrix scored 12/12 on that phrasing
    in isolation, so the unit tests were green while the end-to-end path was unsafe.
    Anything code can determine from the raw text or from the caller's identity must
    not depend on how confident a model happened to be.
    """
    if classification is None:
        return RoutingPlan(triage=True, reason="classification did not complete")

    low = text.lower()

    # --- Override 1: a safety hazard in the actor's own words ------------------
    if detect_safety_critical(text):
        return RoutingPlan(
            agents=["maintenance"],
            reason=(
                "a safety-critical phrase was matched in the raw text, so the maintenance "
                "agent runs regardless of classification confidence"
            ),
        )

    # --- Override 2: the caller is a vendor -----------------------------------
    # A contractor's message is a contractor update whatever it looks like on the
    # surface. Identity is a stronger signal than a keyword score.
    if role == Role.CONTRACTOR:
        return RoutingPlan(
            agents=["contractor"],
            reason="the actor is a contractor, so the contractor agent handles the message",
        )

    # --- Override 3: a site engineer filing a note ----------------------------
    # FR-CON-5: an engineer's free-text note must produce a structured internal
    # summary *and* a customer-safe one, which is the construction agent's job. Read
    # purely on wording these notes look like contractor updates — same vocabulary,
    # same site vernacular — so they were routed to the contractor agent, which
    # produces one internal-only finding and then tried to log a blocker against a
    # staff id that is not a vendor. Identity disambiguates what the words cannot.
    if role == Role.SITE_ENGINEER and classification.intent in {
        Intent.CONTRACTOR_UPDATE,
        Intent.CONSTRUCTION_STATUS,
        Intent.OTHER,
    }:
        return RoutingPlan(
            agents=["construction"],
            reason=(
                "a site engineer filed a progress note, so the construction agent runs and "
                "produces both an internal and a customer-safe summary"
            ),
        )

    # --- Override 4: a sales user asking for their follow-up list -------------
    if role in SALES_ROLES and any(phrase in low for phrase in FOLLOWUP_PHRASES):
        agents = ["followup"]
        if classification.confidence >= confidence_threshold:
            agents += [a for a in ROUTES.get(classification.intent, []) if a not in agents]
        return RoutingPlan(
            agents=agents,
            reason="a sales user asked for a follow-up list; the phrasing is matched in code",
        )

    if classification.confidence < confidence_threshold:
        return RoutingPlan(
            triage=True,
            reason=(
                f"classification confidence {classification.confidence:.2f} is below the "
                f"{confidence_threshold:.2f} threshold, so no specialist is run on a guess"
            ),
        )

    agents = list(ROUTES.get(classification.intent, []))

    if classification.secondary_intent and classification.secondary_intent != classification.intent:
        for agent in ROUTES.get(classification.secondary_intent, []):
            if agent not in agents:
                agents.append(agent)

    if not agents:
        return RoutingPlan(
            agents=[],
            triage=False,
            reason=(
                f"intent {classification.intent.value} has no specialist route; the risk engine and "
                "response agent handle it directly"
            ),
        )

    return RoutingPlan(
        agents=agents,
        reason=f"intent {classification.intent.value} routes to {', '.join(agents)}",
    )
