"""Role capabilities and the no-widening guard."""

from __future__ import annotations

import pytest

from core.enums import Collection, Role
from core.errors import ScopeViolationError
from core.models import AccessScope
from governance import rbac


def test_every_role_has_a_capability_entry() -> None:
    """A role without an entry would silently fall through to an empty scope."""
    for role in Role:
        assert role in rbac.ROLE_CAPABILITIES, f"{role.value} has no capability entry"


def test_external_roles_cannot_read_internal_collections() -> None:
    for role in (Role.PUBLIC_LEAD, Role.CUSTOMER, Role.RESIDENT, Role.BROKER, Role.CONTRACTOR):
        readable = rbac.readable_collections(role)
        assert Collection.PROJECT_REPORTS.value not in readable
        assert Collection.PRICING_SHEETS.value not in readable


def test_manager_can_read_everything() -> None:
    assert set(rbac.readable_collections(Role.MANAGER)) == {c.value for c in Collection}


def test_only_approver_roles_may_approve() -> None:
    assert rbac.may_approve(Role.MANAGER) is True
    assert rbac.may_approve(Role.LEGAL_FINANCE) is True
    assert rbac.may_approve(Role.SITE_ENGINEER) is True
    assert rbac.may_approve(Role.CUSTOMER) is False
    assert rbac.may_approve(Role.BROKER) is False


def test_scope_is_frozen() -> None:
    scope = AccessScope(actor_id="CUST-4471", role=Role.CUSTOMER, booking_ids=["BK-9901"])
    with pytest.raises(Exception):
        scope.booking_ids = ["BK-9902"]  # type: ignore[misc]


def test_widening_is_refused() -> None:
    original = AccessScope(actor_id="CUST-4471", role=Role.CUSTOMER, booking_ids=["BK-9901"])
    widened = AccessScope(
        actor_id="CUST-4471", role=Role.CUSTOMER, booking_ids=["BK-9901", "BK-9902"]
    )
    with pytest.raises(ScopeViolationError):
        rbac.assert_no_widening(original, widened)


def test_identity_change_is_refused() -> None:
    original = AccessScope(actor_id="CUST-4471", role=Role.CUSTOMER)
    other = AccessScope(actor_id="STF-MGR-01", role=Role.MANAGER)
    with pytest.raises(ScopeViolationError):
        rbac.assert_no_widening(original, other)


def test_emptying_project_ids_is_treated_as_widening() -> None:
    """An empty project list means 'all' for internal roles, so it is not a narrowing."""
    original = AccessScope(actor_id="STF-ENG-01", role=Role.SITE_ENGINEER, project_ids=["PRJ-AUR"])
    emptied = AccessScope(actor_id="STF-ENG-01", role=Role.SITE_ENGINEER, project_ids=[])
    with pytest.raises(ScopeViolationError):
        rbac.assert_no_widening(original, emptied)


def test_narrowing_is_allowed() -> None:
    original = AccessScope(
        actor_id="CUST-4471", role=Role.CUSTOMER, booking_ids=["BK-9901", "BK-9902"]
    )
    narrowed = AccessScope(actor_id="CUST-4471", role=Role.CUSTOMER, booking_ids=["BK-9901"])
    rbac.assert_no_widening(original, narrowed)  # must not raise
