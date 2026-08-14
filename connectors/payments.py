"""Payments connector — READ ONLY BY DESIGN.

Design rule #5: there is no code path anywhere in this system that writes a
payment, refund, waiver or discount. `write` raises `NotImplementedError`
unconditionally, and the base class refuses before the network is touched. If a
future requirement needs a payment write, it needs a new connector, a new review
path and a new threat model — not a flag on this one.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from core.models import AccessScope
from connectors.protocol import HttpConnector


class PaymentScheduleQuery(BaseModel):
    booking_id: str


class PaymentMilestoneRecord(BaseModel):
    milestone_id: str
    label: str
    amount: int
    due_date: date
    paid_on: date | None = None
    status: str
    receipt_ref: str | None = None
    seq: int


class PaymentScheduleResult(BaseModel):
    booking_id: str | None = None
    milestones: list[PaymentMilestoneRecord] = []
    total_value: int = 0
    total_paid: int = 0
    total_due: int = 0
    total_overdue: int = 0
    overdue_count: int = 0
    next_due_label: str | None = None
    next_due_date: date | None = None
    found: bool = False


class PaymentsConnector(HttpConnector):
    name = "payments"
    base_path = "/payments"
    read_only = True
    action_risk = {}

    async def query_schedule(
        self, request: PaymentScheduleQuery, scope: AccessScope
    ) -> PaymentScheduleResult:
        data = await self._query("schedule", request.model_dump(mode="json"), scope, use_cache=False)
        return PaymentScheduleResult(**data)

    async def query(self, request: BaseModel, scope: AccessScope) -> BaseModel:
        if isinstance(request, PaymentScheduleQuery):
            return await self.query_schedule(request, scope)
        raise TypeError(f"payments cannot handle {type(request).__name__}")

    async def write(self, action: BaseModel, scope: AccessScope, approval: str | None = None):
        """Always raises. Kept explicit so the refusal is visible in the trace."""
        raise NotImplementedError(
            "The payments integration is read-only by design. No agent path can move money. "
            "Route payment changes to the legal and finance team."
        )
