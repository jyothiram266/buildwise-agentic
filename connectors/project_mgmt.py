"""Project management connector: milestones, site reports, blockers."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from core.enums import RiskTier
from core.errors import PolicyViolationError
from core.models import AccessScope
from connectors.protocol import HttpConnector, WriteResult


class MilestoneQuery(BaseModel):
    project_id: str | None = None
    project_name: str | None = None
    tower_id: str | None = None
    tower_name: str | None = None


class MilestoneRecord(BaseModel):
    milestone_id: str
    name: str
    seq: int
    planned_date: date
    actual_date: date | None = None
    pct_complete: float
    status: str


class TowerProgress(BaseModel):
    tower_id: str
    tower_name: str
    project_id: str
    project_name: str
    floors: int
    status: str
    planned_possession: date | None = None
    #: Present only when a revision has been recorded. Disclosure depends entirely
    #: on `revised_approved`; the agent must never read the date without the flag.
    revised_possession: date | None = None
    revised_approved: bool = False
    milestones: list[MilestoneRecord] = []


class MilestoneResult(BaseModel):
    towers: list[TowerProgress] = []
    found: bool = False
    note: str | None = None


class SiteReportQuery(BaseModel):
    project_id: str | None = None
    tower_id: str | None = None
    limit: int = 4


class SiteReportRecord(BaseModel):
    report_id: str
    project_id: str
    tower_id: str | None = None
    week_of: date
    author: str
    raw_note: str
    approval_status: str
    flagged_injection: bool = False


class SiteReportResult(BaseModel):
    reports: list[SiteReportRecord] = []
    found: bool = False


class BlockerQuery(BaseModel):
    project_id: str | None = None
    work_package_id: str | None = None
    open_only: bool = True


class BlockerRecord(BaseModel):
    blocker_id: str
    project_id: str
    category: str
    description: str
    severity: str
    raised_on: date
    resolved_on: date | None = None
    impacted_milestones: list[str] = []
    vendor_id: str | None = None
    work_package_id: str | None = None


class BlockerResult(BaseModel):
    blockers: list[BlockerRecord] = []
    impacted_milestone_records: list[MilestoneRecord] = []
    found: bool = False


class LogBlockerAction(BaseModel):
    project_id: str
    work_package_id: str | None = None
    vendor_id: str | None = None
    category: str
    description: str
    severity: str
    impacted_milestones: list[str] = []
    raised_by: str


class AttachSummaryAction(BaseModel):
    report_id: str
    internal_summary: str
    customer_summary: str


class ProjectMgmtConnector(HttpConnector):
    name = "project_mgmt"
    base_path = "/pm"
    action_risk = {
        # Recording a blocker is internal bookkeeping and reversible.
        "log_blocker": RiskTier.AUTO_NOTIFY,
        # Attaching a customer-facing summary publishes prose to customers, so it
        # cannot happen without a human approving the text first.
        "attach_summary": RiskTier.DRAFT_APPROVAL,
    }

    async def query_milestones(self, request: MilestoneQuery, scope: AccessScope) -> MilestoneResult:
        data = await self._query("milestones", request.model_dump(mode="json"), scope)
        return MilestoneResult(**data)

    async def query_site_reports(
        self, request: SiteReportQuery, scope: AccessScope
    ) -> SiteReportResult:
        data = await self._query("site_reports", request.model_dump(mode="json"), scope)
        return SiteReportResult(**data)

    async def query_blockers(self, request: BlockerQuery, scope: AccessScope) -> BlockerResult:
        data = await self._query("blockers", request.model_dump(mode="json"), scope)
        return BlockerResult(**data)

    async def query(self, request: BaseModel, scope: AccessScope) -> BaseModel:
        if isinstance(request, MilestoneQuery):
            return await self.query_milestones(request, scope)
        if isinstance(request, SiteReportQuery):
            return await self.query_site_reports(request, scope)
        if isinstance(request, BlockerQuery):
            return await self.query_blockers(request, scope)
        raise TypeError(f"project_mgmt cannot handle {type(request).__name__}")

    async def write(
        self, action: BaseModel, scope: AccessScope, approval: str | None = None
    ) -> WriteResult:
        kind = {LogBlockerAction: "log_blocker", AttachSummaryAction: "attach_summary"}.get(
            type(action)
        )
        if kind is None:
            # PolicyViolationError, not TypeError: refusing an undeclared action is a
            # policy decision, and the API's error handler turns typed domain errors
            # into typed responses. A TypeError here surfaced as a 500.
            raise PolicyViolationError(
                f"project_mgmt has no declared write for {type(action).__name__}; "
                "an action must be declared in action_risk before it can be performed."
            )
        return await self._write(kind, action.model_dump(mode="json"), scope, approval)
