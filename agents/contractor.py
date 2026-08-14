"""Contractor update agent.

Handles vendor-side input: progress, material, manpower, blockers. Three
constraints come straight from the PRD and shape everything here:

* **Delay is always a range with assumptions** (UJ-6). A single number reads as a
  commitment, and a commitment made by an assistant to a vendor is a commercial
  position nobody authorised.
* **No commitment on payment, timeline or scope.** Vendors ask; the agent records
  and names the team that decides. `commitment_requested` is detected in code so
  the risk engine can raise the tier even if the generated text behaves.
* **Internal only.** Everything this agent produces is marked internal: cost,
  vendor performance and dispute detail must not reach a customer channel.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from connectors import registry
from connectors.project_mgmt import BlockerQuery, LogBlockerAction, MilestoneQuery
from core.enums import BlockerCategory, Collection
from core.models import AgentFinding
from orchestration.state import CaseState

from agents.base import BaseAgent

#: Phrases that mean the vendor is asking for something, not just reporting.
COMMITMENT_SIGNALS = (
    "extension", "extend the", "release the payment", "release my payment", "release our payment",
    "when will you release", "when will you pay", "when do we get paid", "payment is pending",
    "clear our invoice", "our payment", "my payment",
    "retention", "additional cost", "escalation in rates", "price revision", "extra claim",
    "when will we be paid", "approve the variation", "revised timeline", "can you confirm",
    "please confirm the date", "waive the penalty", "penalty", "liquidated damages",
)

CATEGORY_SIGNALS: dict[str, tuple[str, ...]] = {
    "material_shortage": ("cement", "steel", "aggregate", "sand", "shortage", "consignment",
                          "supply has stopped", "material not received", "rmc", "batching plant",
                          "stock is", "out of stock"),
    "manpower": ("manpower", "labour", "labourers", "crew", "workers", "gang", "shortage of men",
                 "absent", "migrated"),
    "approval_delay": ("approval", "noc", "sanction", "permission", "clearance", "inspection pending",
                       "authority"),
    "weather": ("rain", "monsoon", "weather", "flooding on site", "waterlogged"),
    "vendor_payment_dispute": ("payment", "invoice", "retention", "dues", "unpaid", "ra bill"),
    "equipment": ("crane", "hoist", "pump", "shuttering", "formwork", "equipment", "breakdown",
                  "machine"),
}

SEVERITY_SIGNALS: dict[str, tuple[str, ...]] = {
    "critical": ("stopped completely", "work has stopped", "cannot proceed", "shut down",
                 "zero stock", "no supply at all"),
    "high": ("halted", "on hold", "critical", "urgent", "severe", "no material", "will stop"),
    "medium": ("slow", "delayed", "partial", "reduced", "shortfall", "behind"),
}


class ContractorOutput(BaseModel):
    blocker_category: str
    severity: str
    impact_statement: str
    delay_estimate_low_days: int = Field(ge=0)
    delay_estimate_high_days: int = Field(ge=0)
    assumptions: list[str] = []
    commitment_requested: bool = False
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)


def detect_category(text: str) -> str:
    """Blocker category from the vendor's words, scored in code.

    Done here rather than trusting the model's field because this value selects
    which milestones are looked up, and a wrong lookup produces a confident
    statement about the wrong part of the project.
    """
    low = text.lower()
    scores = {
        name: sum(1 for signal in signals if signal in low)
        for name, signals in CATEGORY_SIGNALS.items()
    }
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] else "none"


def detect_severity(text: str) -> str:
    low = text.lower()
    for level in ("critical", "high", "medium"):
        if any(signal in low for signal in SEVERITY_SIGNALS[level]):
            return level
    return "low"


class ContractorAgent(BaseAgent):
    name = "contractor"
    prompt_id = "contractor"
    collections = [Collection.POLICIES.value, Collection.PROJECT_REPORTS.value]

    async def _run(self, state: CaseState) -> AgentFinding:
        text = state.masked_input
        category = detect_category(text)
        severity_level = detect_severity(text)
        commitment = any(signal in text.lower() for signal in COMMITMENT_SIGNALS)

        work_package = (
            state.scope.work_package_ids[0] if state.scope.work_package_ids else None
        )
        project_id = state.scope.project_ids[0] if state.scope.project_ids else None

        existing = await registry.project_mgmt().query_blockers(
            BlockerQuery(project_id=project_id, work_package_id=work_package, open_only=True),
            state.scope,
        )
        milestones = await registry.project_mgmt().query_milestones(
            MilestoneQuery(project_id=project_id), state.scope
        )

        impacted = sorted(
            {m for b in existing.blockers for m in b.impacted_milestones}
        ) or self._milestones_in_flight(milestones)

        chunks = await self.retrieve(state, f"{category} blocker escalation procurement policy")

        facts = {
            "work_package_id": work_package,
            "project_id": project_id,
            "detected_category": category,
            "severity": severity_level,
            "commitment_requested": commitment,
            "impacted_milestones": impacted,
            "open_blockers": [b.model_dump(mode="json") for b in existing.blockers],
            "milestone_register": [
                {"milestone_id": m.milestone_id, "name": m.name, "status": m.status,
                 "planned_date": m.planned_date.isoformat(), "pct_complete": m.pct_complete}
                for tower in milestones.towers for m in tower.milestones
            ][:20],
        }

        output = await self.generate(
            state,
            {"facts": facts, "context": self.context_block(chunks), "request": text},
            ContractorOutput,
        )
        assert isinstance(output, ContractorOutput)

        # Code overrides the model's own category and commitment fields. The model
        # is allowed to describe; it is not allowed to decide what gets logged.
        logged_category = category if category != "none" else output.blocker_category
        blocker_id: str | None = None
        logged_category = self._valid_category(logged_category)
        if logged_category and project_id:
            action = LogBlockerAction(
                project_id=project_id,
                work_package_id=work_package,
                vendor_id=state.scope.actor_id,
                category=logged_category,
                description=text[:2000],
                severity=severity_level,
                impacted_milestones=impacted,
                raised_by=state.scope.actor_id,
            )
            result = await registry.project_mgmt().write(action, state.scope)
            blocker_id = result.record_id

        low, high = output.delay_estimate_low_days, output.delay_estimate_high_days
        if high < low:
            low, high = high, low

        return AgentFinding(
            agent=self.name,
            status="ok",
            summary=output.summary,
            structured={
                "blocker_id": blocker_id,
                "blocker_category": logged_category,
                "severity": severity_level,
                "impacted_milestones": impacted,
                "delay_range_days": [low, high] if high else None,
                "assumptions": output.assumptions,
                "commitment_requested": commitment,
                "commitment_made": False,
                "impact_statement": output.impact_statement,
                "work_package_id": work_package,
            },
            citations=self.citations_from(chunks),
            confidence=output.confidence,
            internal_only=True,
        )

    @staticmethod
    def _valid_category(value: str) -> str:
        """Coerce to the enum, or refuse to log rather than invent a category."""
        try:
            return BlockerCategory(value).value
        except ValueError:
            return ""

    @staticmethod
    def _milestones_in_flight(result) -> list[str]:
        return [
            m.milestone_id
            for tower in result.towers
            for m in tower.milestones
            if m.status in {"in_progress", "delayed"}
        ][:5]
