"""Case read routes.

Every query carries the caller's scope as a SQL predicate. A customer asking for a
case list gets their own cases; asking for someone else's returns an empty list
rather than a 403, because a 403 confirms the case exists.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.deps import ScopeDep
from core.enums import EXTERNAL_ROLES, Role
from db import pool

router = APIRouter(prefix="/api/cases", tags=["cases"])

INTERNAL_READ_ALL = {Role.MANAGER, Role.LEGAL_FINANCE, Role.SITE_ENGINEER, Role.SALES_STAFF}


@router.get("")
async def list_cases(scope: ScopeDep, limit: int = 50, status_filter: str | None = None) -> dict:
    clauses, params = [], []
    if scope.role not in INTERNAL_READ_ALL:
        clauses.append(f"actor_id = ${len(params) + 1}")
        params.append(scope.actor_id)
    if status_filter:
        clauses.append(f"status = ${len(params) + 1}")
        params.append(status_filter)
    where = " AND ".join(clauses) if clauses else "TRUE"

    rows = await pool.fetch(
        f"""
        SELECT case_id, actor_id, role, channel, intent, risk_tier, status, masked_input,
               response_mode, confidence, degraded, latency_ms, cost_usd, created_at
        FROM cases WHERE {where} ORDER BY created_at DESC LIMIT {int(min(limit, 200))}
        """,
        *params,
    )
    return {"cases": [_row(r) for r in rows], "count": len(rows)}


@router.get("/{case_id}")
async def get_case(case_id: str, scope: ScopeDep) -> dict:
    row = await pool.fetchrow(
        """
        SELECT case_id, actor_id, role, channel, intent, secondary_intent, entities, sentiment,
               risk_tier, status, masked_input, response_mode, response_text, response_citations,
               findings, confidence, degraded, cost_tokens, cost_usd, latency_ms, created_at
        FROM cases WHERE case_id = $1
        """,
        case_id,
    )
    if row is None or (scope.role not in INTERNAL_READ_ALL and row["actor_id"] != scope.actor_id):
        # Same response for "does not exist" and "not yours".
        raise HTTPException(status.HTTP_404_NOT_FOUND, "case not found")

    record = _row(row)
    record["response_text"] = row["response_text"]
    record["response_citations"] = row["response_citations"]
    record["entities"] = row["entities"]
    if scope.role in EXTERNAL_ROLES:
        record["findings"] = []
    else:
        record["findings"] = row["findings"]
    return record


@router.get("/{case_id}/thread")
async def get_thread(case_id: str, scope: ScopeDep) -> dict:
    rows = await pool.fetch(
        """
        SELECT c.case_id, c.masked_input, c.response_text, c.response_mode, c.risk_tier,
               c.status, c.created_at
        FROM cases c
        WHERE (c.case_id = $1 OR c.thread_of = $1) AND ($2 OR c.actor_id = $3)
        ORDER BY c.created_at
        """,
        case_id,
        scope.role in INTERNAL_READ_ALL,
        scope.actor_id,
    )
    return {"turns": [dict(r) for r in rows]}


def _row(row: Any) -> dict:
    record = dict(row)
    if record.get("confidence") is not None:
        record["confidence"] = float(record["confidence"])
    if record.get("cost_usd") is not None:
        record["cost_usd"] = float(record["cost_usd"])
    return record
