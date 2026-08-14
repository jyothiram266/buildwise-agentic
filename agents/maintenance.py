"""Maintenance agent.

Splits the work along the line design rule #3 draws: the model reads the
complaint and names a category; code assigns priority, team, SLA and warranty
indication, and code decides whether the hazard path fires.

Ticket creation is a tier-0 write (create_ticket), so it happens without a human in
the loop — creating a ticket is reversible and the cost of not creating one is a
resident whose leak is not on anyone's list.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from connectors import registry
from connectors.crm import BookingQuery
from connectors.ticketing import CreateTicketAction
from core.enums import Collection, MaintenanceCategory
from core.models import AgentFinding, MaintenanceAssessment
from governance import audit, severity
from orchestration.state import CaseState

from agents.base import BaseAgent


class MaintenanceOutput(BaseModel):
    category: MaintenanceCategory
    severity_signals: list[str] = []
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)


class MaintenanceAgent(BaseAgent):
    name = "maintenance"
    prompt_id = "maintenance"
    collections = [Collection.POLICIES.value, Collection.FAQ.value]

    async def _run(self, state: CaseState) -> AgentFinding:
        output = await self.generate(
            state, {"request": state.masked_input}, MaintenanceOutput
        )
        assert isinstance(output, MaintenanceOutput)

        # The severity decision reads the resident's own words, not the model's
        # paraphrase: a paraphrase can drop the word that makes it a P1.
        decision = severity.assign_priority(output.category, state.masked_input)

        unit_id = self._unit_for(state)
        possession = await self._possession_date(state)
        warranty = severity.warranty_indication(
            output.category, state.masked_input, possession
        )

        chunks = await self.retrieve(
            state, f"{output.category.value} maintenance service level warranty"
        )

        ticket_id: str | None = None
        sla_due: str | None = None
        if unit_id:
            action = CreateTicketAction(
                unit_id=unit_id,
                raised_by=state.scope.actor_id,
                category=output.category.value,
                priority=decision.priority.value,
                complaint_text=state.masked_input[:2000],
                assigned_team=decision.assigned_team,
                sla_hours=decision.sla_hours,
                warranty_flag=bool(warranty.within_period),
                case_id=state.case_id,
            )
            result = await registry.ticketing().write(action, state.scope)
            ticket_id, sla_due = result.record_id, result.detail

        if decision.safety_critical and decision.on_call_team:
            # Notification is a side channel, not a substitute for the ticket: the
            # on-call team is paged and the ticket still exists for the record.
            await audit.notify_team(
                decision.on_call_team,
                "safety_critical",
                f"{decision.safety_label} reported for unit {unit_id or 'unknown'} "
                f"(case {state.case_id}, ticket {ticket_id or 'pending'}).",
                case_id=state.case_id,
            )

        assessment = MaintenanceAssessment(
            category=output.category,
            priority=decision.priority,
            safety_critical=decision.safety_critical,
            safety_signal=decision.safety_label,
            assigned_team=decision.assigned_team,
            sla_hours=decision.sla_hours,
            warranty_indication=warranty.statement,
            rationale=decision.rationale(),
        )

        summary = self._summary(output, decision, assessment, ticket_id, sla_due, warranty)

        return AgentFinding(
            agent=self.name,
            status="ok",
            summary=summary,
            structured={
                **assessment.model_dump(mode="json"),
                "ticket_id": ticket_id,
                "sla_due": sla_due,
                "response_hours": decision.response_hours,
                "unit_id": unit_id,
                "matched_rule": decision.matched_rule,
                "matched_keywords": decision.matched_keywords,
                "on_call_team": decision.on_call_team,
                "warranty_component": warranty.component,
                "warranty_within_period": warranty.within_period,
                "policy_version": decision.policy_version,
                "model_signals": output.severity_signals,
            },
            citations=self.citations_from(chunks),
            confidence=output.confidence,
        )

    @staticmethod
    def _summary(
        output: MaintenanceOutput,
        decision: severity.SeverityDecision,
        assessment: MaintenanceAssessment,
        ticket_id: str | None,
        sla_due: str | None,
        warranty: severity.WarrantyIndication,
    ) -> str:
        parts = [output.summary]
        if ticket_id:
            parts.append(
                f"Logged as {ticket_id} under {assessment.category.value.replace('_', ' ')} at "
                f"{assessment.priority.value}, assigned to "
                f"{assessment.assigned_team.replace('_', ' ')}."
            )
            if sla_due:
                parts.append(
                    f"The resolution commitment for {assessment.priority.value} is "
                    f"{assessment.sla_hours} hours, due {sla_due}, with first contact within "
                    f"{decision.response_hours} hour(s)."
                )
        else:
            parts.append(
                "No unit is associated with this request, so a ticket has not been created. "
                "A unit reference is needed to raise one."
            )
        if decision.safety_critical:
            parts.append(
                f"This has been treated as safety-critical ({decision.safety_label}) and the "
                f"{decision.on_call_team.replace('_', ' ') if decision.on_call_team else 'on-call'} "
                "team has been alerted directly."
            )
        if warranty.within_period is not None:
            parts.append(warranty.statement)
        return " ".join(parts)

    @staticmethod
    def _unit_for(state: CaseState) -> str | None:
        entities = state.classification.entities if state.classification else {}
        candidate = entities.get("unit")
        if candidate and candidate in state.scope.unit_ids:
            return candidate
        # Falling back to the scope rather than to the named unit is the safe
        # direction: a resident naming someone else's unit gets their own.
        return state.scope.unit_ids[0] if state.scope.unit_ids else None

    @staticmethod
    async def _possession_date(state: CaseState):
        if not state.scope.booking_ids:
            return None
        result = await registry.crm().query_booking(
            BookingQuery(booking_id=state.scope.booking_ids[0]), state.scope
        )
        if not result.found:
            return None
        booking = result.bookings[0]
        if booking.stage == "possession_taken":
            return booking.possession_date
        return None
