"""Payment status agent.

Read-only by construction: the connector it uses has no write path at all (design
rule #5), so no code path here — or anywhere downstream — can record a payment,
issue a refund, apply a waiver or adjust a schedule.

Every figure comes from the payments system. Totals are summed in python from the
returned rows rather than asked for in prose, because an assistant that adds up a
customer's outstanding balance incorrectly has done something worse than refuse.
"""

from __future__ import annotations

from connectors import registry
from connectors.payments import PaymentScheduleQuery
from core.enums import Collection
from core.errors import InsufficientDataError
from core.models import AgentFinding
from orchestration.state import CaseState

from agents.base import BaseAgent

#: Asks this agent must not act on, only route.
WRITE_REQUEST_SIGNALS = (
    "waive", "waiver", "refund", "reverse the", "adjust the", "cancel the demand",
    "reduce the interest", "write off", "settle for", "part payment approval", "extend the due date",
)


class PaymentsAgent(BaseAgent):
    name = "payments"
    collections = [Collection.POLICIES.value, Collection.FAQ.value]

    async def _run(self, state: CaseState) -> AgentFinding:
        entities = state.classification.entities if state.classification else {}
        booking_id = entities.get("booking_id") or (
            state.scope.booking_ids[0] if state.scope.booking_ids else None
        )
        if not booking_id:
            raise InsufficientDataError(
                "No booking is linked to this request, so there is no payment schedule to report."
            )

        result = await registry.payments().query_schedule(
            PaymentScheduleQuery(booking_id=booking_id), state.scope
        )
        if not result.found:
            raise InsufficientDataError(
                f"No payment schedule is visible for booking {booking_id} under this actor's access."
            )

        chunks = await self.retrieve(state, "payment milestone policy demand note interest")
        write_requested = any(sig in state.masked_input.lower() for sig in WRITE_REQUEST_SIGNALS)

        overdue = [m for m in result.milestones if m.status == "overdue"]
        paid = [m for m in result.milestones if m.status == "paid"]

        lines = [
            f"Booking {booking_id} has a total consideration of {_inr(result.total_value)}, of which "
            f"{_inr(result.total_paid)} is recorded as paid across {len(paid)} milestone(s)."
        ]
        if overdue:
            lines.append(
                f"{len(overdue)} milestone(s) totalling {_inr(result.total_overdue)} are past their "
                f"due date: {', '.join(f'{m.label} (due {m.due_date.isoformat()})' for m in overdue[:4])}."
            )
        if result.next_due_label:
            lines.append(
                f"The next scheduled milestone is {result.next_due_label}, due "
                f"{result.next_due_date.isoformat() if result.next_due_date else 'per the schedule'}."
            )
        if not overdue and not result.next_due_label:
            lines.append("Nothing is currently outstanding against the schedule on record.")
        if write_requested:
            # Stated plainly rather than hinted at: the customer needs to know where
            # the request actually goes, and the agent must not imply an outcome.
            lines.append(
                "A change to the amount, the due date or a waiver is not something this channel can "
                "record or approve — the finance team holds that decision and this request has been "
                "passed to them."
            )

        return AgentFinding(
            agent=self.name,
            status="ok",
            summary=" ".join(lines),
            structured={
                "booking_id": booking_id,
                "total_value": result.total_value,
                "total_paid": result.total_paid,
                "total_due": result.total_due,
                "total_overdue": result.total_overdue,
                "overdue_count": len(overdue),
                "next_due_label": result.next_due_label,
                "next_due_date": (
                    result.next_due_date.isoformat() if result.next_due_date else None
                ),
                "write_requested": write_requested,
                "write_performed": False,
                "milestones": [m.model_dump(mode="json") for m in result.milestones],
            },
            citations=self.citations_from(chunks),
            confidence=0.92 if not write_requested else 0.8,
        )


def _inr(amount: int | None) -> str:
    if amount is None:
        return "an amount not on record"
    if amount >= 10_000_000:
        return f"INR {amount:,} ({amount / 10_000_000:.2f} Cr)"
    return f"INR {amount:,} ({amount / 100_000:.2f} L)"
