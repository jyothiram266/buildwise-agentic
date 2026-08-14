"""Classification agent.

Produces intent, entities and a calibrated confidence. It does not route and it
does not decide risk — those are deterministic (design rule #3) and live in
`orchestration/`. Keeping this agent to language understanding is what lets the
router be a table.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from core.enums import Intent
from core.models import AgentFinding, Classification
from orchestration.state import CaseState

from agents.base import BaseAgent


class ClassificationOutput(BaseModel):
    intent: Intent
    secondary_intent: Intent | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    entities: dict[str, str] = {}
    sentiment: Literal["positive", "neutral", "negative"] = "neutral"


class ClassificationAgent(BaseAgent):
    name = "classification"
    prompt_id = "classification"
    collections: list[str] = []  # classification reads no corpus

    async def _run(self, state: CaseState) -> AgentFinding:
        output = await self.generate(
            state,
            {"request": state.masked_input, "channel": state.channel.value},
            ClassificationOutput,
        )
        assert isinstance(output, ClassificationOutput)

        classification = Classification(
            intent=output.intent,
            secondary_intent=output.secondary_intent,
            confidence=output.confidence,
            entities={k: str(v) for k, v in output.entities.items() if v not in (None, "")},
            sentiment=output.sentiment,
        )

        # Structured output is its own grounding: the claim being made is about the
        # text in front of it, not about a fact in a system of record.
        return AgentFinding(
            agent=self.name,
            status="ok",
            summary=(
                f"Classified as {classification.intent.value}"
                + (
                    f" with secondary intent {classification.secondary_intent.value}"
                    if classification.secondary_intent
                    else ""
                )
                + f", sentiment {classification.sentiment}."
            ),
            structured=classification.model_dump(mode="json"),
            confidence=classification.confidence,
        )
