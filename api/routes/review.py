"""Review queue routes: the human-in-the-loop surface.

Authorisation is checked twice — once by the route dependency and again inside
`governance.review_queue.act`. Duplication is intentional: the queue is the control
that makes tier-2 autonomy safe, and a control with a single check has a single
point of failure.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.deps import ApproverDep, ScopeDep
from api.schemas.requests import ReviewActionRequest
from core.errors import PolicyViolationError
from governance import review_queue, sla

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("")
async def list_pending(scope: ScopeDep, tier: int | None = None, limit: int = 50) -> dict:
    items = await review_queue.pending(limit=limit, tier=tier)
    payload = []
    for item in items:
        record = item.model_dump(mode="json")
        if item.sla_due:
            record["sla"] = sla.age_status(item.created_at, item.sla_due).model_dump(mode="json")
        payload.append(record)
    return {"items": payload, "count": len(payload), "viewer_role": scope.role.value}


@router.get("/stats")
async def stats(scope: ScopeDep, window_days: int = 30) -> dict:
    return await review_queue.override_stats(window_days)


@router.get("/{review_id}")
async def get_item(review_id: str, scope: ScopeDep) -> dict:
    item = await review_queue.get_item(review_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "review item not found")
    return item.model_dump(mode="json")


@router.post("/{review_id}/act")
async def act(review_id: str, body: ReviewActionRequest, scope: ApproverDep) -> dict:
    try:
        return await review_queue.act(
            review_id,
            body.action,
            scope.actor_id,
            edited_text=body.edited_text,
            rejection_reason=body.rejection_reason,
            assign_to=body.assign_to,
        )
    except PolicyViolationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.message) from exc


@router.post("/cases/{case_id}/close")
async def close_case(case_id: str, scope: ApproverDep) -> dict:
    """Close a case (FR-ESC-5 guard).

    Refuses while an escalation on the case is unresolved. Nothing automatic can
    reach this route: closing is a human act, recorded as one.
    """
    try:
        return await review_queue.close_case(case_id, scope.actor_id, resolution="closed by staff")
    except PolicyViolationError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, exc.message) from exc


@router.post("/escalations/{esc_id}/resolve")
async def resolve_escalation(esc_id: str, body: dict, scope: ApproverDep) -> dict:
    """Resolve an escalation. Until this happens, the case cannot be closed."""
    try:
        return await review_queue.resolve_escalation(
            esc_id, scope.actor_id, str(body.get("resolution", "")).strip() or "resolved"
        )
    except PolicyViolationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.message) from exc
