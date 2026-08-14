"""Case intake — the single entry point for every channel.

One route for chat, email, WhatsApp and the internal console. The channel is a
field, not a separate code path, so a policy change applies everywhere at once.

Internal roles receive the findings array; external roles do not. That is enforced
here by choosing what to serialise, not by a flag the client is trusted to respect.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.deps import ScopeDep
from api.schemas.requests import IntakeRequest
from api.schemas.responses import CaseResponse, FindingView
from core.enums import EXTERNAL_ROLES
from orchestration.graph import run_case
from orchestration.state import CaseState

router = APIRouter(prefix="/api/cases", tags=["intake"])


def to_response(state: CaseState) -> CaseResponse:
    external = state.scope.role in EXTERNAL_ROLES
    draft = state.response
    return CaseResponse(
        case_id=state.case_id,
        intent=state.classification.intent.value if state.classification else None,
        secondary_intent=(
            state.classification.secondary_intent.value
            if state.classification and state.classification.secondary_intent
            else None
        ),
        risk_tier=int(state.risk_tier) if state.risk_tier is not None else None,
        status=state.status.value,
        mode=draft.mode if draft else None,
        text=draft.text if draft else None,
        citations=draft.citations if draft else [],
        confidence=round(state.min_confidence(), 3),
        findings=(
            []
            if external
            else [
                FindingView(
                    agent=f.agent,
                    status=f.status,
                    summary=f.summary,
                    confidence=f.confidence,
                    internal_only=f.internal_only,
                    citations=f.citations,
                    structured=f.structured,
                )
                for f in state.findings
            ]
        ),
        escalation=state.escalation.model_dump(mode="json") if state.escalation else None,
        degraded=state.degraded,
        degraded_reasons=[] if external else state.degraded_reasons,
        node_log=[] if external else state.node_log,
        latency_ms=state.metadata.get("latency_ms", state.elapsed_ms()),
        cost_usd=state.cost_usd,
        cost_tokens=state.cost_tokens,
        masked_entities=state.metadata.get("masked_entities", []),
    )


@router.post("", response_model=CaseResponse)
async def create_case(body: IntakeRequest, scope: ScopeDep) -> CaseResponse:
    state = await run_case(
        body.text,
        scope,
        channel=body.channel,
        thread_of=body.thread_of,
        attachments=[a.model_dump(mode="json") for a in body.attachments],
    )
    return to_response(state)
