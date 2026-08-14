"""Outbound response bodies."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from core.models import Citation


class FindingView(BaseModel):
    agent: str
    status: str
    summary: str
    confidence: float
    internal_only: bool
    citations: list[Citation] = []
    structured: dict[str, Any] = {}


class CaseResponse(BaseModel):
    """What a chat client renders after one turn."""

    case_id: str
    intent: str | None = None
    secondary_intent: str | None = None
    risk_tier: int | None = None
    status: str
    mode: Literal["auto_send", "draft_for_approval", "acknowledgement_only", "refuse"] | None = None
    text: str | None = None
    citations: list[Citation] = []
    confidence: float | None = None
    #: Present for internal roles only; the chat client for external roles never
    #: receives internal findings, so there is nothing to hide client-side.
    findings: list[FindingView] = []
    escalation: dict[str, Any] | None = None
    degraded: bool = False
    degraded_reasons: list[str] = []
    node_log: list[str] = []
    latency_ms: int = 0
    cost_usd: float = 0.0
    cost_tokens: int = 0
    masked_entities: list[str] = []


class ActorView(BaseModel):
    actor_id: str
    display_name: str
    role: str
    booking_ids: list[str] = []
    unit_ids: list[str] = []
    project_ids: list[str] = []
    work_package_ids: list[str] = []


class TokenResponse(BaseModel):
    token: str
    actor: ActorView
    capabilities: dict[str, Any]
