"""Operations dashboard.

The panels here are the PRD's success metrics, not a generic analytics page. Each
one answers a question someone actually asks in a review:

* Are we escalating the right things, and are we catching them? (tier mix, recall
  proxy, SLA breach)
* Do humans agree with the drafts? (override rate and the reason distribution)
* Is the system honest when it does not know? (refusal and insufficient-data rate)
* What does this cost per case, and where is the latency?
* What does the corpus not cover? (KB gaps)

`refusal_rate` is deliberately shown next to `groundedness`: a system can look
perfectly grounded by refusing everything, and the pair makes that visible.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import ScopeDep
from db import pool
from governance import review_queue

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
async def dashboard(scope: ScopeDep, window_days: int = 30) -> dict:
    window = int(max(1, min(window_days, 365)))
    since = f"now() - interval '{window} days'"

    volume = await pool.fetchrow(
        f"""
        SELECT count(*) AS cases,
               count(*) FILTER (WHERE status = 'answered') AS answered,
               count(*) FILTER (WHERE status = 'awaiting_approval') AS awaiting,
               count(*) FILTER (WHERE status = 'escalated') AS escalated,
               count(*) FILTER (WHERE status = 'failed') AS failed,
               count(*) FILTER (WHERE degraded) AS degraded,
               count(*) FILTER (WHERE response_mode = 'refuse') AS refused,
               avg(latency_ms)::int AS avg_latency_ms,
               -- FR-GOV-4 asks for median response time. That is wall-clock time to
               -- first response, which is a different quantity from pipeline latency:
               -- a tier-2 case answers in 3 seconds and responds when a human
               -- approves it, possibly hours later. Both are reported.
               percentile_disc(0.5) WITHIN GROUP (
                   ORDER BY EXTRACT(EPOCH FROM (first_response_at - created_at))
               ) FILTER (WHERE first_response_at IS NOT NULL) AS median_response_seconds,
               percentile_disc(0.5) WITHIN GROUP (ORDER BY latency_ms) AS median_latency_ms,
               percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95_latency_ms,
               coalesce(sum(cost_usd), 0) AS cost_usd,
               coalesce(sum(cost_tokens), 0) AS tokens,
               avg(confidence) AS avg_confidence
        FROM cases WHERE created_at > {since}
        """
    )
    tiers = await pool.fetch(
        f"SELECT risk_tier, count(*) AS n FROM cases WHERE created_at > {since}"
        " AND risk_tier IS NOT NULL GROUP BY 1 ORDER BY 1"
    )
    intents = await pool.fetch(
        f"""
        SELECT intent, count(*) AS n, avg(confidence)::numeric(4,3) AS avg_confidence
        FROM cases WHERE created_at > {since} AND intent IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
        """
    )
    escalations = await pool.fetch(
        f"""
        SELECT type, owner_team, count(*) AS n,
               count(*) FILTER (WHERE status = 'open' AND sla_due < now()) AS breached,
               count(*) FILTER (WHERE status = 'open') AS open
        FROM escalations WHERE created_at > {since} GROUP BY 1,2 ORDER BY 3 DESC
        """
    )
    tickets = await pool.fetchrow(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE status NOT IN ('resolved','closed') AND sla_due < now())
                   AS breached,
               count(*) FILTER (WHERE priority = 'P1') AS p1,
               count(*) FILTER (WHERE warranty_flag) AS warranty
        FROM tickets
        """
    )
    confidence_bands = await pool.fetch(
        f"""
        SELECT CASE
                 WHEN confidence >= 0.9 THEN '0.9-1.0'
                 WHEN confidence >= 0.8 THEN '0.8-0.9'
                 WHEN confidence >= 0.7 THEN '0.7-0.8'
                 WHEN confidence >= 0.5 THEN '0.5-0.7'
                 ELSE '<0.5'
               END AS band,
               count(*) AS n
        FROM cases WHERE created_at > {since} AND confidence IS NOT NULL
        GROUP BY 1 ORDER BY 1 DESC
        """
    )
    gaps = await pool.fetch(
        f"""
        SELECT query, role, count(*) AS hits FROM kb_gaps WHERE created_at > {since}
        GROUP BY 1,2 ORDER BY 3 DESC LIMIT 8
        """
    )
    cost_by_intent = await pool.fetch(
        f"""
        SELECT intent, coalesce(sum(cost_usd), 0) AS cost_usd, count(*) AS cases,
               coalesce(avg(cost_usd), 0) AS avg_cost_usd
        FROM cases WHERE created_at > {since} AND intent IS NOT NULL
        GROUP BY 1 ORDER BY 2 DESC
        """
    )

    # FR-GOV-4: delayed milestones. Read from the register rather than from cases,
    # because a milestone slips whether or not anyone has asked about it.
    delayed = await pool.fetch(
        """
        SELECT t.name AS tower_name, p.name AS project_name, m.name AS milestone_name,
               m.planned_date, m.actual_date, m.status,
               CASE WHEN m.actual_date IS NOT NULL
                    THEN (m.actual_date - m.planned_date)
                    ELSE (CURRENT_DATE - m.planned_date) END AS slip_days
        FROM milestones m
        JOIN towers t ON t.tower_id = m.tower_id
        JOIN projects p ON p.project_id = t.project_id
        WHERE (m.actual_date IS NULL AND m.planned_date < CURRENT_DATE)
           OR (m.actual_date IS NOT NULL AND m.actual_date > m.planned_date)
        ORDER BY slip_days DESC
        LIMIT 12
        """
    )

    # FR-GOV-4: leads needing follow-up today.
    leads_due = await pool.fetch(
        """
        SELECT lead_id, name, score, stage, next_action, next_action_due,
               (CURRENT_DATE - last_contact) AS days_since_contact
        FROM leads
        WHERE stage NOT IN ('won', 'lost')
          AND (next_action_due <= CURRENT_DATE OR next_action_due IS NULL)
        ORDER BY score DESC, next_action_due NULLS LAST
        LIMIT 12
        """
    )

    # FR-GOV-4: escalation queue ageing, bucketed the way the queue view sorts.
    escalation_ageing = await pool.fetch(
        """
        SELECT CASE
                 WHEN now() - created_at < interval '4 hours'  THEN '<4h'
                 WHEN now() - created_at < interval '24 hours' THEN '4-24h'
                 WHEN now() - created_at < interval '72 hours' THEN '1-3d'
                 ELSE '>3d'
               END AS bucket,
               count(*) AS n,
               count(*) FILTER (WHERE sla_due < now()) AS breached
        FROM escalations WHERE status <> 'resolved'
        GROUP BY 1
        """
    )

    total = int(volume["cases"] or 0)
    overrides = await review_queue.override_stats(window)

    return {
        "window_days": window,
        "volume": {
            "cases": total,
            "answered": int(volume["answered"] or 0),
            "awaiting_approval": int(volume["awaiting"] or 0),
            "escalated": int(volume["escalated"] or 0),
            "failed": int(volume["failed"] or 0),
            "degraded": int(volume["degraded"] or 0),
            "automation_rate": round(int(volume["answered"] or 0) / total, 3) if total else 0.0,
            "escalation_rate": round(int(volume["escalated"] or 0) / total, 3) if total else 0.0,
            # Shown alongside automation: high automation with high refusal is not
            # the same achievement as high automation with low refusal.
            "refusal_rate": round(int(volume["refused"] or 0) / total, 3) if total else 0.0,
        },
        "latency": {
            "avg_ms": int(volume["avg_latency_ms"] or 0),
            "median_ms": int(volume["median_latency_ms"] or 0),
            "p95_ms": int(volume["p95_latency_ms"] or 0),
            "target_p95_ms": 15000,
            "within_target": int(volume["p95_latency_ms"] or 0) <= 15000,
            # Wall-clock to first response, including time spent waiting for a human.
            "median_response_seconds": int(volume["median_response_seconds"] or 0),
        },
        "cost": {
            "total_usd": round(float(volume["cost_usd"] or 0), 4),
            "tokens": int(volume["tokens"] or 0),
            "per_case_usd": round(float(volume["cost_usd"] or 0) / total, 5) if total else 0.0,
            "by_intent": [
                {
                    "intent": r["intent"],
                    "cost_usd": round(float(r["cost_usd"]), 5),
                    "cases": int(r["cases"]),
                    "avg_cost_usd": round(float(r["avg_cost_usd"]), 5),
                }
                for r in cost_by_intent
            ],
        },
        "confidence": {
            "average": round(float(volume["avg_confidence"] or 0), 3),
            "bands": [{"band": r["band"], "count": int(r["n"])} for r in confidence_bands],
        },
        "risk_tiers": [{"tier": int(r["risk_tier"]), "count": int(r["n"])} for r in tiers],
        "intents": [
            {
                "intent": r["intent"],
                "count": int(r["n"]),
                "avg_confidence": float(r["avg_confidence"] or 0),
            }
            for r in intents
        ],
        "escalations": [
            {
                "type": r["type"],
                "owner_team": r["owner_team"],
                "count": int(r["n"]),
                "open": int(r["open"]),
                "sla_breached": int(r["breached"]),
            }
            for r in escalations
        ],
        "human_review": overrides,
        "maintenance": {
            "tickets": int(tickets["total"] or 0),
            "sla_breached": int(tickets["breached"] or 0),
            "p1": int(tickets["p1"] or 0),
            "warranty_flagged": int(tickets["warranty"] or 0),
        },
        "delayed_milestones": [
            {
                "project": r["project_name"],
                "tower": r["tower_name"],
                "milestone": r["milestone_name"],
                "planned_date": r["planned_date"],
                "actual_date": r["actual_date"],
                "status": r["status"],
                "slip_days": int(r["slip_days"] or 0),
            }
            for r in delayed
        ],
        "leads_due_today": [
            {
                "lead_id": r["lead_id"],
                "name": r["name"],
                "score": int(r["score"] or 0),
                "stage": r["stage"],
                "next_action": r["next_action"],
                "next_action_due": r["next_action_due"],
                "days_since_contact": int(r["days_since_contact"] or 0),
            }
            for r in leads_due
        ],
        "escalation_ageing": [
            {"bucket": r["bucket"], "count": int(r["n"]), "sla_breached": int(r["breached"])}
            for r in escalation_ageing
        ],
        "kb_gaps": [
            {"query": r["query"], "role": r["role"], "hits": int(r["hits"])} for r in gaps
        ],
        "targets": {
            "override_rate_max": 0.25,
            "escalation_recall_min": 0.95,
            "groundedness_min": 0.95,
            "acl_leaks_max": 0,
            "p95_latency_ms_max": 15000,
        },
    }


@router.get("/digest/{project_id}")
async def blocker_digest(project_id: str, scope: ScopeDep) -> dict:
    """Daily blocker digest for one project (FR-CTR-3).

    Internal only: every digest carries vendor names and dispute detail, so the
    route refuses external roles outright rather than filtering the payload.
    """
    from fastapi import HTTPException, status

    from core.enums import EXTERNAL_ROLES
    from governance import digest

    if scope.role in EXTERNAL_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "the blocker digest is an internal document"
        )
    result = await digest.build(project_id, scope)
    await digest.record_digest(project_id, result, scope.actor_id)
    return result


@router.get("/digest")
async def all_blocker_digests(scope: ScopeDep) -> dict:
    """One digest per project the caller can see, worst first."""
    from fastapi import HTTPException, status

    from core.enums import EXTERNAL_ROLES
    from governance import digest

    if scope.role in EXTERNAL_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "the blocker digest is an internal document"
        )
    return {"digests": await digest.build_all(scope)}
