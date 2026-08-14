"""Lead follow-up agent (PRD UJ-8).

Produces a ranked action list for a sales user. The ranking is computed in code
from CRM fields and returned with reason codes, because "why is this lead first"
is the only part of a prioritised list that a salesperson can actually check. A
model-generated ordering with a model-generated justification is unfalsifiable.

Scoring inputs and weights are declared below so they can be tuned by the sales
team without touching logic.
"""

from __future__ import annotations

from datetime import date

from connectors import registry
from connectors.crm import LeadQuery, LeadRecord
from core.enums import Collection, Role
from core.errors import InsufficientDataError
from core.models import AgentFinding
from orchestration.state import CaseState

from agents.base import BaseAgent

#: Reason code -> (weight, human explanation). Weights are additive on top of the
#: CRM's own intent score, scaled to the same 0-100 range.
REASON_WEIGHTS: dict[str, tuple[float, str]] = {
    "followup_due": (25.0, "a committed follow-up is due today or overdue"),
    "high_intent": (15.0, "CRM intent score is 75 or above"),
    "site_visit_done": (12.0, "already visited the site"),
    "payment_pending": (20.0, "a payment step is waiting on them"),
    "ageing": (10.0, "no contact for 10 days or more"),
}

FOLLOWUP_SIGNALS = (
    "follow up", "follow-up", "followup", "who should i call", "my leads", "priority list",
    "action list", "today's list", "todays list", "pipeline", "next actions", "chase",
)


def rank(leads: list[LeadRecord], today: date | None = None) -> list[dict]:
    """Rank leads and return the arithmetic alongside each one."""
    today = today or date.today()
    ranked = []
    for lead in leads:
        codes = list(lead.reason_codes)
        if lead.next_action_due and lead.next_action_due <= today and "followup_due" not in codes:
            codes.append("followup_due")
        bonus = sum(REASON_WEIGHTS.get(code, (0.0, ""))[0] for code in codes)
        ranked.append(
            {
                "lead_id": lead.lead_id,
                "name": lead.name,
                "score": round(lead.score + bonus, 1),
                "crm_score": lead.score,
                "priority_bonus": round(bonus, 1),
                "reason_codes": codes,
                "reasons": [REASON_WEIGHTS[c][1] for c in codes if c in REASON_WEIGHTS],
                "next_action": lead.next_action,
                "next_action_due": lead.next_action_due.isoformat() if lead.next_action_due else None,
                "days_since_contact": lead.days_since_contact,
                "interest": lead.interest_config,
                "budget_max": lead.budget_max,
                "project_interest": lead.project_interest,
                "stage": lead.stage,
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["days_since_contact"] or 0))
    return ranked


class FollowUpAgent(BaseAgent):
    name = "followup"
    collections = [Collection.PROPERTY_CATALOG.value, Collection.POLICIES.value]

    async def _run(self, state: CaseState) -> AgentFinding:
        if state.scope.role not in {Role.SALES_STAFF, Role.MANAGER}:
            raise InsufficientDataError(
                "Lead follow-up lists are available to sales users only, and this actor's role does "
                "not include lead access."
            )

        result = await registry.crm().query_leads(
            LeadQuery(
                owner=state.scope.actor_id if state.scope.role == Role.SALES_STAFF else None,
                due_on=date.today(),
                limit=40,
            ),
            state.scope,
        )
        if not result.leads:
            return AgentFinding(
                agent=self.name,
                status="ok",
                summary="No open leads are due for follow-up against the current criteria.",
                structured={"count": 0, "ranked": []},
                confidence=0.9,
            )

        ranked = rank(result.leads)[:10]
        lines = [f"{len(ranked)} follow-up(s) ranked by priority:"]
        for index, item in enumerate(ranked, start=1):
            lines.append(
                f"{index}. {item['name']} ({item['lead_id']}) — score {item['score']} "
                f"[{', '.join(item['reason_codes']) or 'base score only'}]; next action "
                f"{item['next_action'] or 'not set'}"
                + (f", due {item['next_action_due']}" if item["next_action_due"] else "")
                + "."
            )

        return AgentFinding(
            agent=self.name,
            status="ok",
            summary="\n".join(lines),
            structured={
                "count": len(ranked),
                "ranked": ranked,
                "weights": {k: v[0] for k, v in REASON_WEIGHTS.items()},
            },
            confidence=0.9,
            internal_only=True,
        )
