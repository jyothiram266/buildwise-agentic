"""Ticketing connector: maintenance tickets, SLA windows, assignment history."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from core.enums import RiskTier
from core.errors import PolicyViolationError
from core.models import AccessScope
from connectors.protocol import HttpConnector, WriteResult


class TicketQuery(BaseModel):
    ticket_id: str | None = None
    unit_id: str | None = None
    status: str | None = None
    open_only: bool = False
    limit: int = 20


class TicketRecord(BaseModel):
    ticket_id: str
    unit_id: str | None = None
    category: str
    priority: str
    complaint_text: str
    assigned_team: str
    status: str
    warranty_flag: bool = False
    created_at: datetime
    sla_due: datetime
    resolved_at: datetime | None = None
    sla_breached: bool = False


class TicketResult(BaseModel):
    tickets: list[TicketRecord] = []
    match_count: int = 0
    found: bool = False


class CreateTicketAction(BaseModel):
    unit_id: str
    raised_by: str
    category: str
    priority: str
    complaint_text: str
    assigned_team: str
    sla_hours: int
    warranty_flag: bool = False
    case_id: str | None = None


class TicketingConnector(HttpConnector):
    name = "ticketing"
    base_path = "/ticketing"
    action_risk = {
        # PRD Section 9 places standard maintenance ticket creation at tier 0: it
        # records a request, commits nothing, and not creating it is the worse
        # outcome for the resident.
        "create_ticket": RiskTier.AUTO,
        "reassign": RiskTier.AUTO_NOTIFY,
    }

    async def query_tickets(self, request: TicketQuery, scope: AccessScope) -> TicketResult:
        data = await self._query("tickets", request.model_dump(mode="json"), scope, use_cache=False)
        return TicketResult(**data)

    async def query(self, request: BaseModel, scope: AccessScope) -> BaseModel:
        if isinstance(request, TicketQuery):
            return await self.query_tickets(request, scope)
        raise TypeError(f"ticketing cannot handle {type(request).__name__}")

    async def create_ticket(
        self, action: CreateTicketAction, scope: AccessScope, approval: str | None = None
    ) -> WriteResult:
        return await self._write("create_ticket", action.model_dump(mode="json"), scope, approval)

    async def write(
        self, action: BaseModel, scope: AccessScope, approval: str | None = None
    ) -> WriteResult:
        if not isinstance(action, CreateTicketAction):
            # PolicyViolationError, not TypeError: refusing an undeclared action is a
            # policy decision, and the API's error handler turns typed domain errors
            # into typed responses. A TypeError here surfaced as a 500.
            raise PolicyViolationError(
                f"ticketing has no declared write for {type(action).__name__}; "
                "an action must be declared in action_risk before it can be performed."
            )
        return await self.create_ticket(action, scope, approval)
