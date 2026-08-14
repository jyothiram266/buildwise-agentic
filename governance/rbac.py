"""Identity to authorisation.

Design rule #2 says authorisation sits below the model. That means the scope is
resolved once, at the edge, from the identity directory — never from anything the
actor typed, and never from anything a model produced.

Two properties this module guarantees:

* **No widening.** `AccessScope` is frozen, and the only constructor here reads
  from the `actors` table. A caller that wants a bigger scope has to ask for a
  different identity, which is an auditable act, rather than mutating a field.
* **Role capabilities are data, not scattered conditionals.** `ROLE_CAPABILITIES`
  maps the architecture Section 6.1 table into one dict that both the API and the
  agents consult, so a change to what a broker may see is a one-line change.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from api.config import get_logger, get_settings
from core.enums import Collection, Role
from core.errors import ScopeViolationError
from core.models import AccessScope
from db import pool

log = get_logger(__name__)

#: Architecture Section 6.1, as data. `collections` is the corpus a role may read;
#: `systems` is the set of connectors it may reach at all.
ROLE_CAPABILITIES: dict[Role, dict[str, Any]] = {
    # Published price sheets are customer-facing by design: FR-PROP-2 requires
    # quoting approved pricing with its effective date to a prospect, and UJ-1 is
    # exactly that. The sheets carry "Approved for customer quotation" and contain no
    # cost or margin data — what stays internal is `project_reports`, not price.
    # Omitting PRICING_SHEETS here contradicted the corpus `audience_scope`, and the
    # inconsistency showed up as an ACL test failure rather than as a leak.
    Role.PUBLIC_LEAD: {
        "collections": [Collection.PROPERTY_CATALOG, Collection.PRICING_SHEETS, Collection.FAQ],
        "systems": ["crm_inventory"],
        "own_records_only": False,
        "may_approve": False,
    },
    Role.CUSTOMER: {
        "collections": [
            Collection.PROPERTY_CATALOG,
            Collection.PRICING_SHEETS,
            Collection.DOC_CHECKLISTS,
            Collection.POLICIES,
            Collection.FAQ,
        ],
        "systems": ["crm_booking", "payments", "dms", "project_mgmt_public", "ticketing"],
        "own_records_only": True,
        "may_approve": False,
    },
    Role.RESIDENT: {
        "collections": [Collection.POLICIES, Collection.FAQ, Collection.DOC_CHECKLISTS],
        "systems": ["ticketing", "crm_booking", "payments", "dms"],
        "own_records_only": True,
        "may_approve": False,
    },
    Role.BROKER: {
        "collections": [Collection.PROPERTY_CATALOG, Collection.PRICING_SHEETS, Collection.FAQ],
        "systems": ["crm_inventory"],
        "own_records_only": False,
        "may_approve": False,
    },
    Role.CONTRACTOR: {
        "collections": [Collection.POLICIES],
        "systems": ["project_mgmt_own_wp"],
        "own_records_only": True,
        "may_approve": False,
    },
    Role.SALES_STAFF: {
        "collections": [
            Collection.PROPERTY_CATALOG,
            Collection.PRICING_SHEETS,
            Collection.DOC_CHECKLISTS,
            Collection.POLICIES,
            Collection.FAQ,
        ],
        "systems": ["crm_inventory", "crm_booking", "crm_leads", "payments", "dms"],
        "own_records_only": False,
        "may_approve": True,
    },
    Role.SITE_ENGINEER: {
        "collections": [Collection.PROJECT_REPORTS, Collection.POLICIES],
        "systems": ["project_mgmt", "ticketing"],
        "own_records_only": False,
        "may_approve": True,
    },
    Role.LEGAL_FINANCE: {
        "collections": [
            Collection.POLICIES,
            Collection.DOC_CHECKLISTS,
            Collection.PRICING_SHEETS,
            Collection.PROJECT_REPORTS,
        ],
        "systems": ["dms", "payments", "crm_booking", "project_mgmt"],
        "own_records_only": False,
        "may_approve": True,
    },
    Role.MANAGER: {
        "collections": list(Collection),
        "systems": ["crm_inventory", "crm_booking", "crm_leads", "payments", "dms",
                    "project_mgmt", "ticketing"],
        "own_records_only": False,
        "may_approve": True,
    },
}


def readable_collections(role: Role) -> list[str]:
    caps = ROLE_CAPABILITIES.get(role)
    if caps is None:
        raise ScopeViolationError(f"no capability entry for role {role.value}")
    return [c.value if isinstance(c, Collection) else str(c) for c in caps["collections"]]


def may_approve(role: Role) -> bool:
    return bool(ROLE_CAPABILITIES.get(role, {}).get("may_approve"))


def may_use_system(role: Role, system: str) -> bool:
    return system in ROLE_CAPABILITIES.get(role, {}).get("systems", [])


async def scope_for_actor(actor_id: str) -> AccessScope:
    """Build the scope from the identity directory.

    Raises rather than defaulting to an empty scope: silently degrading an unknown
    actor to public access is how a broken login turns into a data-shaped bug
    instead of a loud failure.
    """
    row = await pool.fetchrow(
        """
        SELECT actor_id, role, booking_ids, unit_ids, project_ids, work_package_ids
        FROM actors WHERE actor_id = $1
        """,
        actor_id,
    )
    if row is None:
        raise ScopeViolationError(f"unknown actor {actor_id!r}; no scope can be issued")
    try:
        role = Role(row["role"])
    except ValueError as exc:
        raise ScopeViolationError(f"actor {actor_id!r} has unrecognised role {row['role']!r}") from exc

    return AccessScope(
        actor_id=row["actor_id"],
        role=role,
        booking_ids=list(row["booking_ids"] or []),
        unit_ids=list(row["unit_ids"] or []),
        project_ids=list(row["project_ids"] or []),
        work_package_ids=list(row["work_package_ids"] or []),
    )


async def list_actors() -> list[dict[str, Any]]:
    """Backs the demo role switcher. Read-only view of the identity directory."""
    rows = await pool.fetch(
        "SELECT actor_id, display_name, role, booking_ids, unit_ids, project_ids,"
        " work_package_ids FROM actors ORDER BY role, actor_id"
    )
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Tokens
#
# A short-lived signed token carrying only the actor id. The scope is looked up
# server-side on every request: a scope embedded in a token is a scope that keeps
# working after the underlying permission was revoked.
# ---------------------------------------------------------------------------


def issue_token(actor_id: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": actor_id,
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def actor_from_token(token: str) -> str:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "sub", "iss"]},
        )
    except jwt.PyJWTError as exc:
        raise ScopeViolationError(f"token rejected: {type(exc).__name__}") from exc
    subject = payload.get("sub")
    if not subject:
        raise ScopeViolationError("token carries no subject")
    return str(subject)


async def scope_from_token(token: str) -> AccessScope:
    return await scope_for_actor(actor_from_token(token))


def assert_no_widening(original: AccessScope, proposed: AccessScope) -> None:
    """Guard for any code path that rebuilds a scope mid-flight.

    Used by the graph when it reconstructs state from a checkpoint. The check is
    cheap and catches the class of bug that would otherwise be invisible.
    """
    if proposed.actor_id != original.actor_id or proposed.role != original.role:
        raise ScopeViolationError(
            f"scope identity changed mid-case: {original.actor_id}/{original.role.value} "
            f"-> {proposed.actor_id}/{proposed.role.value}"
        )
    for field in ("booking_ids", "unit_ids", "project_ids", "work_package_ids"):
        before, after = set(getattr(original, field)), set(getattr(proposed, field))
        # An empty project_ids means "all" for internal roles, so narrowing to
        # empty is a widening in disguise.
        if field == "project_ids" and before and not after:
            raise ScopeViolationError("project_ids was emptied, which widens access for this role")
        if after - before:
            raise ScopeViolationError(
                f"scope widened on {field}: added {sorted(after - before)}"
            )
