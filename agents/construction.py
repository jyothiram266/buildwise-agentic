"""Construction status agent.

Three things are deliberately not left to a model:

* **Slippage.** `compute_slippage` is pure python (PRD FR-CON-4). A model asked to
  compare a planned date to an actual date will occasionally produce a number that
  is nearly right, and nearly right is worse than absent for a possession date.
* **Which date may be spoken.** `revised_possession` is only disclosable when
  `revised_approved` is true. The check is a field test here, and the mock server
  additionally strips the value for external roles, so two independent layers have
  to fail before an unapproved date reaches a customer.
* **Audience separation.** For an external actor only the customer-safe generation
  runs, so internal cost, vendor and safety detail is never in the same context
  window as the customer prose. For an internal actor both summaries are produced,
  which is what UJ-5 needs: one note in, two outputs.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from connectors import registry
from connectors.project_mgmt import BlockerQuery, MilestoneQuery, SiteReportQuery, TowerProgress
from core.enums import Collection, Role
from core.errors import InsufficientDataError
from core.models import AgentFinding, SlippageAssessment, utcnow
from orchestration.state import CaseState

from agents.base import BaseAgent

INTERNAL_AUDIENCES = {Role.SITE_ENGINEER, Role.MANAGER, Role.LEGAL_FINANCE, Role.SALES_STAFF}

#: The vocabulary a customer-facing update may use for a cause. Anything more
#: specific (a vendor name, a payment dispute) is internal by classification.
CAUSE_CATEGORIES = {
    "material_shortage": "material supply",
    "manpower": "manpower availability",
    "approval_delay": "statutory approvals",
    "weather": "weather",
    "vendor_payment_dispute": "contractor coordination",
    "equipment": "equipment availability",
    "design_change": "design revisions",
}


class ConstructionOutput(BaseModel):
    summary: str
    next_action: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


def compute_slippage(tower: TowerProgress, today: date | None = None) -> SlippageAssessment:
    """Deterministic progress and slippage. No model involvement.

    A milestone is late if it has no actual date and its planned date has passed,
    or if it completed after its planned date. Slip is measured in days against
    plan, and the largest slip in the chain is what the possession date feels.
    """
    today = today or utcnow().date()
    total = len(tower.milestones)
    complete = sum(1 for m in tower.milestones if m.status == "complete")
    pct = round(sum(m.pct_complete for m in tower.milestones) / total, 1) if total else 0.0

    slips: list[tuple[str, int]] = []
    for milestone in tower.milestones:
        if milestone.actual_date and milestone.actual_date > milestone.planned_date:
            slips.append((milestone.name, (milestone.actual_date - milestone.planned_date).days))
        elif not milestone.actual_date and milestone.planned_date < today:
            slips.append((milestone.name, (today - milestone.planned_date).days))

    max_slip = max((days for _, days in slips), default=0)
    return SlippageAssessment(
        tower_id=tower.tower_id,
        tower_name=tower.tower_name,
        milestones_total=total,
        milestones_complete=complete,
        pct_complete=pct,
        max_slip_days=max_slip,
        slipped_milestones=[name for name, _ in sorted(slips, key=lambda s: -s[1])],
        flagged=max_slip >= 14,
        approved_revised_possession=(
            tower.revised_possession if tower.revised_approved else None
        ),
    )


class ConstructionAgent(BaseAgent):
    name = "construction"
    collections = [Collection.PROJECT_REPORTS.value, Collection.PROPERTY_CATALOG.value,
                   Collection.POLICIES.value]

    async def _run(self, state: CaseState) -> AgentFinding:
        entities = state.classification.entities if state.classification else {}
        internal = state.scope.role in INTERNAL_AUDIENCES

        result = await registry.project_mgmt().query_milestones(
            MilestoneQuery(
                tower_name=entities.get("tower"),
                project_name=entities.get("project"),
                project_id=(state.scope.project_ids[0] if state.scope.project_ids else None),
            ),
            state.scope,
        )
        if not result.found:
            raise InsufficientDataError(
                "No tower matching this request is visible, so no construction position can be "
                "reported. Naming the project or tower would let this be answered."
            )

        tower = self._pick_tower(result.towers, entities)
        assessment = compute_slippage(tower)
        current, nxt = self._current_and_next(tower)

        blockers = await registry.project_mgmt().query_blockers(
            BlockerQuery(project_id=tower.project_id, open_only=True), state.scope
        )
        causes = sorted(
            {CAUSE_CATEGORIES.get(b.category, b.category) for b in blockers.blockers}
        )

        chunks = await self.retrieve(
            state, f"{tower.project_name} {tower.tower_name} construction progress milestone"
        )

        customer_facts = {
            "tower_name": tower.tower_name,
            "project_name": tower.project_name,
            "pct_complete": assessment.pct_complete,
            "milestones_complete": assessment.milestones_complete,
            "milestones_total": assessment.milestones_total,
            "current_milestone": current,
            "next_milestone": nxt,
            "last_certified": self._last_certified(tower),
            "planned_possession": tower.planned_possession.isoformat() if tower.planned_possession else None,
            # Only the approved date is even present in the customer-facing facts.
            "approved_revised_possession": (
                assessment.approved_revised_possession.isoformat()
                if assessment.approved_revised_possession
                else None
            ),
            "slip_days": assessment.max_slip_days,
            "cause_categories": causes,
            "stale": any(c.is_stale for c in chunks),
        }

        customer = await self.generate(
            state,
            {
                "facts": customer_facts,
                "context": self.context_block(
                    [c for c in chunks if c.collection != Collection.PROJECT_REPORTS]
                ),
                "request": state.masked_input,
            },
            ConstructionOutput,
            prompt_id="construction_customer",
        )
        assert isinstance(customer, ConstructionOutput)

        if not internal:
            return AgentFinding(
                agent=self.name,
                status="ok",
                summary=customer.summary,
                structured={
                    **customer_facts,
                    "unapproved_revision_withheld": bool(
                        tower.revised_possession and not tower.revised_approved
                    ),
                    "next_action": customer.next_action,
                },
                citations=self.citations_from(chunks),
                confidence=customer.confidence,
                internal_only=False,
            )

        reports = await registry.project_mgmt().query_site_reports(
            SiteReportQuery(project_id=tower.project_id, tower_id=tower.tower_id, limit=3),
            state.scope,
        )
        internal_facts = {
            **customer_facts,
            "slipped_milestones": assessment.slipped_milestones,
            "flagged": assessment.flagged,
            "unapproved_revised_possession": (
                tower.revised_possession.isoformat()
                if tower.revised_possession and not tower.revised_approved
                else None
            ),
            "blockers": [b.model_dump(mode="json") for b in blockers.blockers],
            "report_excerpts": [r.raw_note[:600] for r in reports.reports],
            "injection_flagged": any(r.flagged_injection for r in reports.reports),
        }

        internal_out = await self.generate(
            state,
            {
                "facts": internal_facts,
                "context": self.context_block(chunks),
                "request": state.masked_input,
            },
            ConstructionOutput,
            prompt_id="construction_internal",
        )
        assert isinstance(internal_out, ConstructionOutput)

        return AgentFinding(
            agent=self.name,
            status="ok",
            summary=internal_out.summary,
            structured={
                **internal_facts,
                # Carried so UJ-5 can queue both texts from one run.
                "customer_summary": customer.summary,
                "next_action": internal_out.next_action,
            },
            citations=self.citations_from(chunks),
            confidence=min(internal_out.confidence, customer.confidence),
            internal_only=True,
        )

    @staticmethod
    def _pick_tower(towers: list[TowerProgress], entities: dict[str, str]) -> TowerProgress:
        wanted = (entities.get("tower") or "").strip().lower()
        if wanted:
            for tower in towers:
                if wanted in tower.tower_name.lower() or wanted == tower.tower_id.lower():
                    return tower
        return towers[0]

    @staticmethod
    def _current_and_next(tower: TowerProgress) -> tuple[str | None, str | None]:
        ordered = sorted(tower.milestones, key=lambda m: m.seq)
        current = next((m.name for m in ordered if m.status == "in_progress"), None)
        if current is None:
            current = next((m.name for m in ordered if m.status != "complete"), None)
        upcoming = next(
            (m.name for m in ordered if m.status not in {"complete", "in_progress"}), None
        )
        return current, upcoming

    @staticmethod
    def _last_certified(tower: TowerProgress) -> str | None:
        dates = [m.actual_date for m in tower.milestones if m.actual_date]
        return max(dates).isoformat() if dates else None
