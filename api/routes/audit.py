"""Audit and replay routes.

Restricted to roles that can already see internal detail: a trace contains every
retrieved source and every agent's reasoning, which is more than a customer's own
case view should expose.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.deps import ScopeDep
from core.enums import Role
from db import pool
from governance import audit
from governance.policy_registry import get_registry

router = APIRouter(prefix="/api/audit", tags=["audit"])

AUDIT_ROLES = {Role.MANAGER, Role.LEGAL_FINANCE, Role.SITE_ENGINEER}


def _guard(scope) -> None:
    if scope.role not in AUDIT_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "audit access is limited to internal roles")


@router.get("/{case_id}")
async def replay(case_id: str, scope: ScopeDep) -> dict:
    _guard(scope)
    result = await audit.replay(case_id)
    if not result.get("found"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")
    return result


@router.get("/{case_id}/trace")
async def trace(case_id: str, scope: ScopeDep) -> dict:
    _guard(scope)
    return {"case_id": case_id, "trace": await audit.trace_for_case(case_id)}


@router.get("/versions/registry")
async def versions(scope: ScopeDep) -> dict:
    """What is deployed right now: every prompt and policy version in use."""
    _guard(scope)
    registry = get_registry()
    return {
        "prompts": registry.list_prompts(),
        "policies": {
            policy_id: registry.policy_version(policy_id)
            for policy_id in ("severity_matrix", "escalation_matrix", "warranty_policy")
        },
    }


@router.get("/gaps/kb")
async def kb_gaps(scope: ScopeDep, limit: int = 50) -> dict:
    """Queries that retrieved nothing — the content team's backlog."""
    _guard(scope)
    rows = await pool.fetch(
        """
        SELECT query, collections, role, count(*) AS hits, max(created_at) AS last_seen
        FROM kb_gaps GROUP BY query, collections, role
        ORDER BY hits DESC, last_seen DESC LIMIT $1
        """,
        int(min(limit, 200)),
    )
    return {"gaps": [dict(r) for r in rows]}
