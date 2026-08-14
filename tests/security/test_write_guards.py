"""Write guards: what the system refuses to do at all."""

from __future__ import annotations

import pytest

from connectors import registry
from connectors.payments import PaymentsConnector
from connectors.project_mgmt import AttachSummaryAction
from core.errors import ApprovalRequiredError, PolicyViolationError

pytestmark = [pytest.mark.security, pytest.mark.anyio]


async def test_payments_has_no_write_path(scopes) -> None:
    """Design rule #5. The connector refuses before any network call happens."""
    connector = PaymentsConnector()
    with pytest.raises(NotImplementedError):
        await connector.write(object(), scopes["manager"])  # type: ignore[arg-type]


async def test_payments_connector_is_marked_read_only() -> None:
    assert PaymentsConnector().read_only is True


async def test_tier_two_write_without_approval_is_refused(scopes) -> None:
    """The connector checks approval itself, not the caller."""
    action = AttachSummaryAction(
        report_id="SR-0001", internal_summary="internal", customer_summary="customer"
    )
    with pytest.raises(ApprovalRequiredError):
        await registry.project_mgmt().write(action, scopes["site_engineer"], approval=None)


async def test_undeclared_action_is_refused(scopes) -> None:
    from pydantic import BaseModel

    class MadeUpAction(BaseModel):
        anything: str = "x"

    with pytest.raises((PolicyViolationError, KeyError)):
        await registry.crm().write(MadeUpAction(), scopes["manager"])
