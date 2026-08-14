"""CRM connector: inventory, customers, bookings, leads, interactions."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from core.enums import RiskTier
from core.errors import PolicyViolationError
from core.models import AccessScope
from connectors.protocol import HttpConnector, WriteResult


# --- typed requests ---------------------------------------------------------
class InventoryQuery(BaseModel):
    config: str | None = None
    city: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    budget_max: int | None = None
    budget_min: int | None = None
    status: str = "available"
    limit: int = 10


class BookingQuery(BaseModel):
    booking_id: str | None = None
    customer_id: str | None = None


class LeadQuery(BaseModel):
    owner: str | None = None
    due_on: date | None = None
    min_score: int = 0
    limit: int = 25


# --- typed responses --------------------------------------------------------
class UnitRecord(BaseModel):
    unit_id: str
    project_id: str
    project_name: str
    tower_name: str
    city: str
    locality: str | None = None
    config: str
    carpet_area: int
    floor: int
    facing: str | None = None
    status: str
    base_price: int
    all_in_price: int
    price_ref: str


class InventoryResult(BaseModel):
    units: list[UnitRecord] = []
    match_count: int = 0
    total_in_project: int = 0
    price_ref: str | None = None
    price_effective_date: date | None = None
    project_status: str | None = None
    config_exists_in_project: bool = True
    note: str | None = None


class BookingRecord(BaseModel):
    booking_id: str
    customer_id: str
    customer_name: str
    unit_id: str
    project_id: str
    project_name: str
    tower_name: str
    config: str
    stage: str
    agreement_status: str
    booked_on: date | None = None
    possession_date: date | None = None
    possession_date_approved: bool = True
    total_value: int
    sales_owner: str | None = None


class BookingResult(BaseModel):
    bookings: list[BookingRecord] = []
    found: bool = False


class LeadRecord(BaseModel):
    lead_id: str
    name: str
    interest_config: str | None = None
    budget_max: int | None = None
    city: str | None = None
    project_interest: str | None = None
    score: int
    stage: str
    site_visit_done: bool
    last_contact: date | None = None
    days_since_contact: int | None = None
    next_action: str | None = None
    next_action_due: date | None = None
    reason_codes: list[str] = []


class LeadResult(BaseModel):
    leads: list[LeadRecord] = []
    match_count: int = 0


class CreateLeadAction(BaseModel):
    name: str
    contact_email: str | None = None
    contact_phone: str | None = None
    interest_config: str | None = None
    budget_max: int | None = None
    city: str | None = None
    project_interest: str | None = None
    source: str = "web_chat"
    next_action: str = "site_visit_offer"


class LogInteractionAction(BaseModel):
    lead_id: str | None = None
    customer_id: str | None = None
    summary: str
    channel: str


class CrmConnector(HttpConnector):
    name = "crm"
    base_path = "/crm"
    action_risk = {
        # Creating a lead and logging a contact are routine, reversible and
        # customer-initiated, so they are tier 0/1. Anything that changes a
        # customer's commercial position is not in this connector at all.
        "create_lead": RiskTier.AUTO,
        "log_interaction": RiskTier.AUTO,
        "set_followup": RiskTier.AUTO_NOTIFY,
        # A booking-stage change alters the customer's contractual position.
        "update_booking_stage": RiskTier.DRAFT_APPROVAL,
    }

    async def query_inventory(self, request: InventoryQuery, scope: AccessScope) -> InventoryResult:
        data = await self._query("inventory", request.model_dump(mode="json"), scope)
        return InventoryResult(**data)

    async def query_booking(self, request: BookingQuery, scope: AccessScope) -> BookingResult:
        data = await self._query("booking", request.model_dump(mode="json"), scope, use_cache=False)
        return BookingResult(**data)

    async def query_leads(self, request: LeadQuery, scope: AccessScope) -> LeadResult:
        data = await self._query("leads", request.model_dump(mode="json"), scope, use_cache=False)
        return LeadResult(**data)

    async def query(self, request: BaseModel, scope: AccessScope) -> BaseModel:
        """Protocol entry point; dispatches on the request type."""
        if isinstance(request, InventoryQuery):
            return await self.query_inventory(request, scope)
        if isinstance(request, BookingQuery):
            return await self.query_booking(request, scope)
        if isinstance(request, LeadQuery):
            return await self.query_leads(request, scope)
        raise TypeError(f"crm cannot handle {type(request).__name__}")

    async def write(
        self, action: BaseModel, scope: AccessScope, approval: str | None = None
    ) -> WriteResult:
        kind = {
            CreateLeadAction: "create_lead",
            LogInteractionAction: "log_interaction",
        }.get(type(action))
        if kind is None:
            # PolicyViolationError, not TypeError: refusing an undeclared action is a
            # policy decision, and the API's error handler turns typed domain errors
            # into typed responses. A TypeError here surfaced as a 500.
            raise PolicyViolationError(
                f"crm has no declared write for {type(action).__name__}; "
                "an action must be declared in action_risk before it can be performed."
            )
        return await self._write(kind, action.model_dump(mode="json"), scope, approval)
