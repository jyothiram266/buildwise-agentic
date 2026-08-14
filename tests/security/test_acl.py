"""Access control, tested as a property rather than a code path.

Every case here follows the same shape: give the request a scope that should not
see something, and assert the *data* comes back empty. Asserting on an exception
would be weaker — the requirement is that the system cannot tell the difference
between "not yours" and "does not exist", because a distinguishable error is itself
a disclosure.

Marked `security` and `integration`: these need the seeded database and the mock
connector service, since the whole point is to exercise the real SQL predicates.
"""

from __future__ import annotations

import pytest

from connectors import registry
from connectors.crm import BookingQuery, LeadQuery
from connectors.dms import DocumentQuery
from connectors.payments import PaymentScheduleQuery
from connectors.project_mgmt import MilestoneQuery, SiteReportQuery
from connectors.ticketing import TicketQuery
from core.enums import Collection, Role
from core.models import AccessScope
from retrieval import search

pytestmark = [pytest.mark.security, pytest.mark.integration, pytest.mark.anyio]


async def test_customer_cannot_read_another_booking(scopes) -> None:
    """CUST-4471 owns BK-9901. Asking for BK-9902 must return nothing at all."""
    result = await registry.crm().query_booking(BookingQuery(booking_id="BK-9902"), scopes["customer"])
    assert result.found is False
    assert result.bookings == []


async def test_customer_reads_their_own_booking(scopes) -> None:
    result = await registry.crm().query_booking(BookingQuery(booking_id="BK-9901"), scopes["customer"])
    assert result.found is True
    assert result.bookings[0].booking_id == "BK-9901"


async def test_payment_schedule_is_scoped(scopes) -> None:
    mine = await registry.payments().query_schedule(
        PaymentScheduleQuery(booking_id="BK-9901"), scopes["customer"]
    )
    theirs = await registry.payments().query_schedule(
        PaymentScheduleQuery(booking_id="BK-9902"), scopes["customer"]
    )
    assert mine.found is True
    assert theirs.found is False
    assert theirs.milestones == []


async def test_documents_are_scoped(scopes) -> None:
    result = await registry.dms().query_documents(
        DocumentQuery(booking_id="BK-9902"), scopes["customer"]
    )
    assert result.documents == []


async def test_resident_sees_only_their_own_tickets(scopes) -> None:
    result = await registry.ticketing().query_tickets(TicketQuery(limit=50), scopes["resident"])
    unit_ids = {ticket.unit_id for ticket in result.tickets}
    assert unit_ids <= set(scopes["resident"].unit_ids)


async def test_site_reports_are_invisible_to_external_roles(scopes) -> None:
    for role in ("customer", "resident", "broker", "contractor", "public_lead"):
        result = await registry.project_mgmt().query_site_reports(
            SiteReportQuery(project_id="PRJ-AUR"), scopes[role]
        )
        assert result.reports == [], f"{role} received raw site reports"


async def test_site_engineer_can_read_site_reports(scopes) -> None:
    result = await registry.project_mgmt().query_site_reports(
        SiteReportQuery(project_id="PRJ-AUR"), scopes["site_engineer"]
    )
    assert result.found is True


async def test_leads_are_sales_only(scopes) -> None:
    for role in ("customer", "broker", "resident", "contractor", "public_lead"):
        result = await registry.crm().query_leads(LeadQuery(limit=10), scopes[role])
        assert result.leads == [], f"{role} received the lead pipeline"
    assert (await registry.crm().query_leads(LeadQuery(limit=10), scopes["sales_staff"])).leads


async def test_unapproved_possession_date_never_leaves_the_connector(scopes) -> None:
    """Tower E has an unapproved revision. External roles must not receive the value."""
    for role in ("customer", "resident", "broker", "contractor", "public_lead"):
        result = await registry.project_mgmt().query_milestones(
            MilestoneQuery(tower_name="Tower E"), scopes[role]
        )
        for tower in result.towers:
            if not tower.revised_approved:
                assert tower.revised_possession is None, (
                    f"{role} received an unapproved revised possession date"
                )


async def test_internal_roles_do_receive_the_unapproved_date(scopes) -> None:
    """The value exists and is visible internally; only disclosure is restricted."""
    result = await registry.project_mgmt().query_milestones(
        MilestoneQuery(tower_name="Tower E"), scopes["manager"]
    )
    towers = [t for t in result.towers if not t.revised_approved and t.revised_possession]
    assert towers, "expected the seeded unapproved revision to be visible to a manager"


async def test_contractor_sees_only_their_own_work_packages(scopes) -> None:
    from connectors.project_mgmt import BlockerQuery

    result = await registry.project_mgmt().query_blockers(
        BlockerQuery(project_id="PRJ-AUR", open_only=True), scopes["contractor"]
    )
    for blocker in result.blockers:
        assert blocker.work_package_id in scopes["contractor"].work_package_ids


async def test_retrieval_respects_audience_scope(scopes) -> None:
    """Internal collections must not appear in an external actor's results.

    `project_reports` is the internal collection — it carries the milestone register,
    vendor detail and unapproved dates. `pricing_sheets` is deliberately *not* on
    this list: FR-PROP-2 requires quoting approved pricing to a prospect, and the
    published sheets are marked "Approved for customer quotation". An earlier version
    of this test asserted the opposite and was wrong about the requirement.
    """
    for role in ("public_lead", "customer", "resident", "broker", "contractor"):
        chunks = await search.search("milestone register internal progress", scopes[role], k=20)
        collections = {chunk.collection for chunk in chunks}
        assert Collection.PROJECT_REPORTS not in collections, f"{role} retrieved project reports"


async def test_pricing_reaching_external_roles_carries_no_internal_data(scopes) -> None:
    """If a price sheet is customer-facing, its content must earn that.

    The protection is not "hide the collection" but "publish only quotable figures",
    so this asserts the property that makes the disclosure safe.
    """
    forbidden = ("internal cost", "margin", "cost per square", "procurement", "landed cost")
    for role in ("public_lead", "customer", "broker"):
        chunks = await search.search(
            "price list per square foot", scopes[role],
            collections=[Collection.PRICING_SHEETS.value], k=20,
        )
        for chunk in chunks:
            low = chunk.content.lower()
            for term in forbidden:
                assert term not in low, f"{role} received a sheet containing {term!r}"


async def test_retrieval_is_project_scoped_for_customers(scopes) -> None:
    chunks = await search.search("possession timeline", scopes["customer"], k=20)
    for chunk in chunks:
        assert chunk.project_id in (None, *scopes["customer"].project_ids)


async def test_public_lead_cannot_reach_a_booking(scopes) -> None:
    lead = AccessScope(actor_id="LEAD-0001", role=Role.PUBLIC_LEAD)
    result = await registry.crm().query_booking(BookingQuery(booking_id="BK-9901"), lead)
    assert result.bookings == []
