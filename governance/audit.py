"""Append-only audit trail and replay.

Architecture Section 6.2 lists what every record must carry. The point of the list
is a specific capability: given a case id, reconstruct exactly which prompt
version, policy version, model and source documents produced the answer that was
sent. `replay()` is that capability, and its existence is what makes the trace
worth writing.

Nothing here updates or deletes. The table enforces it with a trigger too, because
a guarantee that lives only in application code is a guarantee until the next
migration script.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from api.config import get_logger
from core.models import TraceRecord, utcnow
from db import pool

log = get_logger(__name__)


def inputs_hash(payload: Any) -> str:
    """Stable hash of an agent's inputs.

    Hashed rather than stored: inputs contain the actor's text, and the trace is
    read by staff across teams. The hash proves two runs saw the same input
    without republishing that input in a second place.
    """
    serialised = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()[:32]


async def record(
    case_id: str,
    agent: str,
    *,
    inputs: Any,
    output: dict[str, Any] | None = None,
    prompt_version: str | None = None,
    policy_version: str | None = None,
    model: str | None = None,
    retrieved_source_ids: list[str] | None = None,
    confidence: float | None = None,
    risk_tier: int | None = None,
    decision: str | None = None,
    human_actor: str | None = None,
    latency_ms: int = 0,
    tokens: int = 0,
    cost_usd: float = 0.0,
) -> str:
    """Write one trace row. Returns the trace id."""
    trace_id = f"TRC-{uuid.uuid4().hex[:16]}"
    await pool.execute(
        """
        INSERT INTO agent_trace (trace_id, case_id, agent, prompt_version, policy_version, model,
                                 inputs_hash, retrieved_source_ids, output, confidence, risk_tier,
                                 decision, human_actor, latency_ms, tokens, cost_usd, ts)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
        """,
        trace_id,
        case_id,
        agent,
        prompt_version,
        policy_version,
        model,
        inputs_hash(inputs),
        retrieved_source_ids or [],
        pool.to_jsonb(output or {}),
        confidence,
        risk_tier,
        decision,
        human_actor,
        latency_ms,
        tokens,
        cost_usd,
        utcnow(),
    )
    return trace_id


async def record_model(trace: TraceRecord) -> str:
    return await record(
        trace.case_id,
        trace.agent,
        inputs=trace.inputs_hash,
        output=trace.output,
        prompt_version=trace.prompt_version,
        policy_version=trace.policy_version,
        model=trace.model,
        retrieved_source_ids=trace.retrieved_source_ids,
        confidence=trace.confidence,
        risk_tier=trace.risk_tier,
        decision=trace.decision,
        human_actor=trace.human_actor,
        latency_ms=trace.latency_ms,
        tokens=trace.tokens,
        cost_usd=trace.cost_usd,
    )


async def trace_for_case(case_id: str) -> list[dict[str, Any]]:
    rows = await pool.fetch(
        """
        SELECT trace_id, seq, agent, prompt_version, policy_version, model, inputs_hash,
               retrieved_source_ids, output, confidence, risk_tier, decision, human_actor,
               latency_ms, tokens, cost_usd, ts
        FROM agent_trace WHERE case_id = $1 ORDER BY seq
        """,
        case_id,
    )
    return [dict(r) for r in rows]


async def replay(case_id: str) -> dict[str, Any]:
    """Reconstruct a case decision path from the trace alone.

    Deliberately reads only `cases`, `agent_trace`, `escalations` and
    `review_queue` — the same tables an auditor would be given. If a step cannot
    be explained from those rows, that is a defect in the trace, and this function
    is where it becomes visible.
    """
    case = await pool.fetchrow(
        """
        SELECT case_id, actor_id, role, channel, intent, secondary_intent, entities, sentiment,
               risk_tier, status, masked_input, response_mode, response_text, response_citations,
               confidence, degraded, cost_tokens, cost_usd, latency_ms, created_at, first_response_at
        FROM cases WHERE case_id = $1
        """,
        case_id,
    )
    if case is None:
        return {"case_id": case_id, "found": False}

    trace = await trace_for_case(case_id)
    escalation = await pool.fetchrow(
        "SELECT esc_id, type, owner_team, sla_hours, sla_due, status, assigned_to, brief"
        " FROM escalations WHERE case_id = $1",
        case_id,
    )
    review = await pool.fetchrow(
        "SELECT review_id, status, action, acted_by, acted_at, rejection_reason,"
        " edited_text IS NOT NULL AS was_edited FROM review_queue WHERE case_id = $1",
        case_id,
    )

    steps = [
        {
            "seq": int(row["seq"]),
            "agent": row["agent"],
            "decision": row["decision"],
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            "risk_tier": row["risk_tier"],
            "prompt_version": row["prompt_version"],
            "policy_version": row["policy_version"],
            "model": row["model"],
            "sources": list(row["retrieved_source_ids"] or []),
            "latency_ms": row["latency_ms"],
            "tokens": row["tokens"],
            "cost_usd": float(row["cost_usd"] or 0),
            "human_actor": row["human_actor"],
            "output": row["output"],
            "at": row["ts"],
        }
        for row in trace
    ]

    versions = {
        "prompts": sorted({s["prompt_version"] for s in steps if s["prompt_version"]}),
        "policies": sorted({s["policy_version"] for s in steps if s["policy_version"]}),
        "models": sorted({s["model"] for s in steps if s["model"]}),
    }
    sources = sorted({sid for s in steps for sid in s["sources"]})

    return {
        "case_id": case_id,
        "found": True,
        "case": dict(case),
        "steps": steps,
        "versions": versions,
        "sources_used": sources,
        "escalation": dict(escalation) if escalation else None,
        "human_review": dict(review) if review else None,
        "reproducible": bool(steps) and all(
            s["prompt_version"] or s["agent"] in {"masking", "router", "risk_engine", "graph", "gate"}
            for s in steps
        ),
    }


async def log_kb_gap(query: str, collections: list[str], role: str, case_id: str | None) -> None:
    """A query that retrieved nothing is a content problem, not just a bad answer."""
    await pool.execute(
        "INSERT INTO kb_gaps (case_id, query, collections, role) VALUES ($1,$2,$3,$4)",
        case_id,
        query[:500],
        collections,
        role,
    )
    log.info("kb_gap_logged", role=role, collections=collections)


async def notify_team(team: str, kind: str, message: str, case_id: str | None = None) -> None:
    """Stand-in for the real notification bus, recorded so demos can show it fired."""
    await pool.execute(
        "INSERT INTO team_notifications (case_id, team, kind, message) VALUES ($1,$2,$3,$4)",
        case_id,
        team,
        kind,
        message[:2000],
    )
    log.info("team_notified", team=team, kind=kind, case_id=case_id)
