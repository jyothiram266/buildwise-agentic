"""The human review queue.

Design rule #4 says uncertainty is an output. This module is where that output
lands: a tier-2 draft or tier-3 escalation becomes a row a named person acts on.

Two decisions worth stating:

* **Approval produces a token, not a boolean.** The connector validates the token
  itself (design rule, AGENTS.md Section 5), so approval cannot be asserted by the
  code path that wants to perform the write. Tokens are single-use.
* **Rejection requires a reason from a fixed set.** Free-text rejection produces
  no signal. A closed set produces a distribution that tells the team which agent
  to fix — which is the whole point of tracking override rate.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Any

from api.config import get_logger
from core.enums import RejectionReason, ReviewAction, RiskTier, Role
from core.errors import PolicyViolationError
from core.models import ApprovalToken, Citation, ReviewItem, utcnow
from db import pool
from governance import audit, rbac

log = get_logger(__name__)


async def enqueue(
    *,
    case_id: str,
    risk_tier: RiskTier,
    audience: Role,
    original_request: str,
    reasoning_summary: str,
    proposed_response: str,
    confidence: float,
    citations: list[Citation] | None = None,
    sla_due: datetime | None = None,
    assigned_to: str | None = None,
) -> ReviewItem:
    """Place a draft in front of a human. Idempotent per case."""
    existing = await pool.fetchrow(
        "SELECT review_id FROM review_queue WHERE case_id = $1 AND status = 'pending'", case_id
    )
    if existing:
        return await get_item(existing["review_id"])  # type: ignore[return-value]

    review_id = f"REV-{uuid.uuid4().hex[:12]}"
    await pool.execute(
        """
        INSERT INTO review_queue (review_id, case_id, risk_tier, audience, original_request,
                                  reasoning_summary, citations, proposed_response, confidence,
                                  sla_due, assigned_to)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        """,
        review_id,
        case_id,
        int(risk_tier),
        audience.value,
        original_request,
        reasoning_summary,
        pool.to_jsonb([c.model_dump(mode="json") for c in (citations or [])]),
        proposed_response,
        round(confidence, 3),
        sla_due,
        assigned_to,
    )
    await audit.record(
        case_id,
        "review_queue",
        inputs={"risk_tier": int(risk_tier), "audience": audience.value},
        output={"review_id": review_id},
        decision="queued_for_human",
        risk_tier=int(risk_tier),
    )
    log.info("review_enqueued", case_id=case_id, review_id=review_id, tier=int(risk_tier))
    return await get_item(review_id)  # type: ignore[return-value]


def _to_item(row: dict[str, Any]) -> ReviewItem:
    return ReviewItem(
        review_id=row["review_id"],
        case_id=row["case_id"],
        risk_tier=RiskTier(int(row["risk_tier"])),
        audience=Role(row["audience"]),
        original_request=row["original_request"],
        reasoning_summary=row["reasoning_summary"],
        citations=[Citation.model_validate(c) for c in (row["citations"] or [])],
        proposed_response=row["proposed_response"],
        confidence=float(row["confidence"]),
        sla_due=row["sla_due"],
        status=row["status"],
        action=ReviewAction(row["action"]) if row["action"] else None,
        acted_by=row["acted_by"],
        acted_at=row["acted_at"],
        rejection_reason=(
            RejectionReason(row["rejection_reason"]) if row["rejection_reason"] else None
        ),
        edited_text=row["edited_text"],
        assigned_to=row["assigned_to"],
        created_at=row["created_at"],
    )


async def get_item(review_id: str) -> ReviewItem | None:
    row = await pool.fetchrow("SELECT * FROM review_queue WHERE review_id = $1", review_id)
    return _to_item(dict(row)) if row else None


async def pending(limit: int = 50, tier: int | None = None) -> list[ReviewItem]:
    """Oldest SLA first — the queue orders itself by urgency, not arrival."""
    clause = "status = 'pending'"
    params: list[Any] = []
    if tier is not None:
        clause += " AND risk_tier = $1"
        params.append(tier)
    rows = await pool.fetch(
        f"SELECT * FROM review_queue WHERE {clause} "
        f"ORDER BY sla_due NULLS LAST, created_at LIMIT {int(limit)}",
        *params,
    )
    return [_to_item(dict(r)) for r in rows]


async def issue_approval(
    case_id: str, approved_by: str, action_kind: str, risk_tier: RiskTier
) -> ApprovalToken:
    """Mint a single-use approval token for one action on one case."""
    token = f"APV-{secrets.token_urlsafe(24)}"
    await pool.execute(
        """
        INSERT INTO approval_tokens (token, case_id, approved_by, action_kind, risk_tier)
        VALUES ($1,$2,$3,$4,$5)
        """,
        token,
        case_id,
        approved_by,
        action_kind,
        int(risk_tier),
    )
    return ApprovalToken(
        token=token,
        case_id=case_id,
        approved_by=approved_by,
        action_kind=action_kind,
        risk_tier=risk_tier,
    )


async def has_open_escalation(case_id: str) -> bool:
    """Is a human still on the hook for this case?

    FR-ESC-5: an escalated case is never closed autonomously. This is the single
    predicate that enforces it, so every path that would close a case has to ask.
    """
    return bool(
        await pool.fetchval(
            "SELECT 1 FROM escalations WHERE case_id = $1 AND status <> 'resolved' LIMIT 1",
            case_id,
        )
    )


async def close_case(case_id: str, actor_id: str, resolution: str) -> dict[str, Any]:
    """Close a case. Refuses while an escalation is open.

    Deliberately the only way a case reaches `closed`: the graph can mark a case
    answered, but answered is not closed, and nothing automatic crosses that line.
    """
    if await has_open_escalation(case_id):
        raise PolicyViolationError(
            "this case has an open escalation and cannot be closed until the owning team "
            "resolves it (FR-ESC-5)",
            case_id=case_id,
        )
    scope = await rbac.scope_for_actor(actor_id)
    if not rbac.may_approve(scope.role):
        raise PolicyViolationError(f"role {scope.role.value} may not close cases", case_id=case_id)

    await pool.execute(
        "UPDATE cases SET status = 'closed', closed_at = now() WHERE case_id = $1", case_id
    )
    await audit.record(
        case_id,
        "case_close",
        inputs={"actor_id": actor_id},
        output={"resolution": resolution[:500]},
        decision="closed",
        human_actor=actor_id,
    )
    log.info("case_closed", case_id=case_id, actor=actor_id)
    return {"case_id": case_id, "status": "closed"}


async def resolve_escalation(
    esc_id: str, actor_id: str, resolution: str
) -> dict[str, Any]:
    """Resolve an escalation. Only a human does this, and it is recorded as such."""
    scope = await rbac.scope_for_actor(actor_id)
    if not rbac.may_approve(scope.role):
        raise PolicyViolationError(f"role {scope.role.value} may not resolve escalations")

    row = await pool.fetchrow(
        "SELECT case_id, status FROM escalations WHERE esc_id = $1", esc_id
    )
    if row is None:
        raise PolicyViolationError(f"unknown escalation {esc_id!r}")
    if row["status"] == "resolved":
        raise PolicyViolationError(f"escalation {esc_id} is already resolved")

    await pool.execute(
        """
        UPDATE escalations SET status = 'resolved', resolution = $2, resolved_at = now(),
               assigned_to = COALESCE(assigned_to, $3)
        WHERE esc_id = $1
        """,
        esc_id,
        resolution[:2000],
        actor_id,
    )
    await audit.record(
        row["case_id"],
        "escalation_resolved",
        inputs={"esc_id": esc_id},
        output={"resolution": resolution[:500]},
        decision="escalation_resolved",
        human_actor=actor_id,
    )
    return {"esc_id": esc_id, "case_id": row["case_id"], "status": "resolved"}


async def act(
    review_id: str,
    action: ReviewAction,
    actor_id: str,
    *,
    edited_text: str | None = None,
    rejection_reason: RejectionReason | None = None,
    assign_to: str | None = None,
) -> dict[str, Any]:
    """Record a human decision and, where it sends something, produce the token.

    Authorisation is checked here rather than at the route so that any future
    caller — a batch tool, a Slack action — cannot bypass it.
    """
    item = await get_item(review_id)
    if item is None:
        raise PolicyViolationError(f"unknown review item {review_id!r}")
    if item.status != "pending":
        raise PolicyViolationError(
            f"review {review_id} was already {item.status}; a second decision is not permitted"
        )

    scope = await rbac.scope_for_actor(actor_id)
    if not rbac.may_approve(scope.role):
        raise PolicyViolationError(
            f"role {scope.role.value} may not act on review items", case_id=item.case_id
        )
    if action == ReviewAction.REJECT and rejection_reason is None:
        raise PolicyViolationError("rejection requires a reason from the fixed set")
    if action == ReviewAction.EDIT_AND_SEND and not (edited_text or "").strip():
        raise PolicyViolationError("edit_and_send requires the edited text")

    status = {
        ReviewAction.APPROVE: "approved",
        ReviewAction.EDIT_AND_SEND: "edited",
        ReviewAction.REJECT: "rejected",
        ReviewAction.REASSIGN: "reassigned",
    }[action]

    await pool.execute(
        """
        UPDATE review_queue
        SET status = $2, action = $3, acted_by = $4, acted_at = now(),
            rejection_reason = $5, edited_text = $6,
            assigned_to = COALESCE($7, assigned_to)
        WHERE review_id = $1
        """,
        review_id,
        status,
        action.value,
        actor_id,
        rejection_reason.value if rejection_reason else None,
        edited_text,
        assign_to,
    )

    sent_text: str | None = None
    token: ApprovalToken | None = None
    if action in {ReviewAction.APPROVE, ReviewAction.EDIT_AND_SEND}:
        sent_text = edited_text if action == ReviewAction.EDIT_AND_SEND else item.proposed_response
        token = await issue_approval(item.case_id, actor_id, "send_response", item.risk_tier)
        await pool.execute(
            """
            UPDATE cases SET status = 'answered', response_text = $2, response_mode = $3,
                   first_response_at = COALESCE(first_response_at, now())
            WHERE case_id = $1
            """,
            item.case_id,
            sent_text,
            "human_approved" if action == ReviewAction.APPROVE else "human_edited",
        )
    elif action == ReviewAction.REJECT:
        await pool.execute("UPDATE cases SET status = 'rejected' WHERE case_id = $1", item.case_id)

    await audit.record(
        item.case_id,
        "human_review",
        inputs={"review_id": review_id, "action": action.value},
        output={
            "status": status,
            "rejection_reason": rejection_reason.value if rejection_reason else None,
            "edited": action == ReviewAction.EDIT_AND_SEND,
            "assigned_to": assign_to,
        },
        decision=action.value,
        risk_tier=int(item.risk_tier),
        human_actor=actor_id,
    )
    log.info("review_acted", review_id=review_id, action=action.value, actor=actor_id)

    return {
        "review_id": review_id,
        "status": status,
        "sent_text": sent_text,
        "approval_token": token.token if token else None,
    }


async def override_stats(window_days: int = 30) -> dict[str, Any]:
    """Override rate and the reason distribution behind it.

    Override rate is a product metric (PRD: under 25%), but the reason breakdown is
    the actionable half: 'wrong_tone' and 'missing_context' point at different fixes.
    """
    row = await pool.fetchrow(
        f"""
        SELECT count(*) AS total,
               count(*) FILTER (WHERE action IN ('edit_and_send','reject')) AS overridden,
               count(*) FILTER (WHERE action = 'approve') AS approved,
               count(*) FILTER (WHERE action = 'edit_and_send') AS edited,
               count(*) FILTER (WHERE action = 'reject') AS rejected
        FROM review_queue
        WHERE acted_at IS NOT NULL AND acted_at > now() - interval '{int(window_days)} days'
        """
    )
    reasons = await pool.fetch(
        f"""
        SELECT rejection_reason AS reason, count(*) AS n FROM review_queue
        WHERE rejection_reason IS NOT NULL
          AND acted_at > now() - interval '{int(window_days)} days'
        GROUP BY 1 ORDER BY 2 DESC
        """
    )
    total = int(row["total"] or 0)
    return {
        "window_days": window_days,
        "decided": total,
        "approved": int(row["approved"] or 0),
        "edited": int(row["edited"] or 0),
        "rejected": int(row["rejected"] or 0),
        "override_rate": round(int(row["overridden"] or 0) / total, 3) if total else 0.0,
        "target": 0.25,
        "reasons": [{"reason": r["reason"], "count": int(r["n"])} for r in reasons],
        "pending": int(
            await pool.fetchval("SELECT count(*) FROM review_queue WHERE status = 'pending'") or 0
        ),
    }
