"""Document management connector: submitted documents, status, expiry."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from core.enums import RiskTier
from core.errors import PolicyViolationError
from core.models import AccessScope
from connectors.protocol import HttpConnector, WriteResult


class DocumentQuery(BaseModel):
    booking_id: str
    stage: str | None = None


class DocumentRecord(BaseModel):
    doc_id: str
    type: str
    status: str
    stage: str
    submitted_on: date | None = None
    expires_on: date | None = None
    days_to_expiry: int | None = None


class DocumentResult(BaseModel):
    booking_id: str | None = None
    stage: str | None = None
    documents: list[DocumentRecord] = []
    submitted: list[str] = []
    pending: list[str] = []
    expired: list[str] = []
    found: bool = False


class FlagMissingAction(BaseModel):
    booking_id: str
    doc_types: list[str]
    note: str | None = None


class DmsConnector(HttpConnector):
    name = "dms"
    base_path = "/dms"
    action_risk = {
        # Flagging a gap is an internal annotation; it changes no customer position.
        "flag_missing": RiskTier.AUTO_NOTIFY,
    }

    async def query_documents(self, request: DocumentQuery, scope: AccessScope) -> DocumentResult:
        data = await self._query("documents", request.model_dump(mode="json"), scope, use_cache=False)
        return DocumentResult(**data)

    async def query(self, request: BaseModel, scope: AccessScope) -> BaseModel:
        if isinstance(request, DocumentQuery):
            return await self.query_documents(request, scope)
        raise TypeError(f"dms cannot handle {type(request).__name__}")

    async def write(
        self, action: BaseModel, scope: AccessScope, approval: str | None = None
    ) -> WriteResult:
        if not isinstance(action, FlagMissingAction):
            # PolicyViolationError, not TypeError: refusing an undeclared action is a
            # policy decision, and the API's error handler turns typed domain errors
            # into typed responses. A TypeError here surfaced as a 500.
            raise PolicyViolationError(
                f"dms has no declared write for {type(action).__name__}; "
                "an action must be declared in action_risk before it can be performed."
            )
        return await self._write("flag_missing", action.model_dump(mode="json"), scope, approval)
