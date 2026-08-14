"""Escalation agent.

Writes the brief a human reads before taking over, and records the escalation row
that starts the SLA clock. It does not decide whether to escalate — that decision
is already made deterministically in `orchestration/risk_engine.py` — so the
agent's job is narrow: explain, route, and start the clock.

The order matters. The escalation row and the SLA clock are written *before* the
brief is generated, so a model failure cannot swallow an escalation. A case that
should have reached a human always reaches one, even with an unusable brief
attached.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from core.enums import EscalationType
from core.models import AgentFinding, EscalationDecision, utcnow
from db import pool
from governance import audit, sla
from orchestration.risk_engine import RiskAssessment
from orchestration.state import CaseState

from agents.base import BaseAgent


class EscalationBriefOutput(BaseModel):
    brief: str
    confidence: float = Field(ge=0.0, le=1.0)


class EscalationAgent(BaseAgent):
    name = "escalation"
    prompt_id = "escalation_brief"
    collections: list[str] = []

    async def _run(self, state: CaseState) -> AgentFinding:  # pragma: no cover - see run_with
        raise NotImplementedError("call run_with(state, assessment)")

    async def run_with(self, state: CaseState, assessment: RiskAssessment) -> AgentFinding:
        """Record the escalation, then write the brief."""
        escalation_type = assessment.escalation_type or EscalationType.LOW_CONFIDENCE
        owner_team = assessment.owner_team or "customer_relations"
        sla_hours = assessment.sla_hours or 12
        esc_id = f"ESC-{uuid.uuid4().hex[:12]}"
        due = sla.due_at(sla_hours)

        # Clock first. If generation fails after this point the case is still owned,
        # still timed, and still visible in the queue.
        await pool.execute(
            """
            INSERT INTO escalations (esc_id, case_id, type, owner_team, sla_hours, sla_due, brief)
            VALUES ($1,$2,$3,$4,$5,$6,$7)
            ON CONFLICT (esc_id) DO NOTHING
            """,
            esc_id,
            state.case_id,
            escalation_type.value,
            owner_team,
            sla_hours,
            due,
            "(brief pending)",
        )
        await audit.notify_team(
            owner_team,
            f"escalation_{escalation_type.value}",
            f"Case {state.case_id} escalated as {escalation_type.value}; response due "
            f"{due.isoformat()}.",
            case_id=state.case_id,
        )

        prior = await self._prior_contacts(state)
        facts = {
            "case_id": state.case_id,
            "channel": state.channel.value,
            "actor_role": state.scope.role.value,
            "actor_id": state.scope.actor_id,
            "intent": state.classification.intent.value if state.classification else None,
            "secondary_intent": (
                state.classification.secondary_intent.value
                if state.classification and state.classification.secondary_intent
                else None
            ),
            "risk_tier": int(assessment.tier),
            "escalation_type": escalation_type.value,
            "owner_team": owner_team,
            "sla_hours": sla_hours,
            "sla_due": due.isoformat(),
            "triggers": assessment.triggers,
            "gaps": assessment.gaps,
            "prior_contacts": prior,
            "findings": [
                {
                    "agent": f.agent,
                    "status": f.status,
                    "summary": f.summary,
                    "confidence": f.confidence,
                    "internal_only": f.internal_only,
                    "structured": f.structured,
                }
                for f in state.findings
            ],
        }

        try:
            output = await self.generate(
                state, {"facts": facts, "request": state.masked_input}, EscalationBriefOutput
            )
            assert isinstance(output, EscalationBriefOutput)
            brief, confidence = output.brief, output.confidence
        except Exception:  # noqa: BLE001 - the escalation itself must survive
            brief = self._fallback_brief(facts)
            confidence = 0.5

        await pool.execute("UPDATE escalations SET brief = $2 WHERE esc_id = $1", esc_id, brief)

        decision = EscalationDecision(
            required=True,
            escalation_type=escalation_type.value,
            owner_team=owner_team,
            sla_hours=sla_hours,
            brief=brief,
            rationale=assessment.rationale,
        )

        return AgentFinding(
            agent=self.name,
            status="ok",
            summary=f"Escalated as {escalation_type.value} to {owner_team}, response due in "
            f"{sla_hours}h ({due.isoformat()}).",
            structured={
                "esc_id": esc_id,
                "decision": decision.model_dump(mode="json"),
                "sla_due": due.isoformat(),
                "triggers": assessment.triggers,
                "policy_version": assessment.policy_version,
            },
            confidence=confidence,
            internal_only=True,
        )

    @staticmethod
    async def _prior_contacts(state: CaseState) -> int:
        """Repeat contact is a service-failure signal worth putting in the brief."""
        return int(
            await pool.fetchval(
                """
                SELECT count(*) FROM cases
                WHERE actor_id = $1 AND case_id <> $2 AND created_at > now() - interval '24 hours'
                """,
                state.scope.actor_id,
                state.case_id,
            )
            or 0
        )

    @staticmethod
    def _fallback_brief(facts: dict) -> str:
        """Deterministic brief used when generation fails.

        Terse and factual. Better a plain brief than a missing escalation.
        """
        findings = "\n".join(
            f"- {f['agent']}: {f['status']} — {str(f['summary'])[:200]}" for f in facts["findings"]
        ) or "- No specialist findings were produced."
        return (
            f"## Case history\n\n{facts['actor_role']} raised case {facts['case_id']} via "
            f"{facts['channel']}, classified as {facts['intent']}.\n\n"
            f"## What was attempted\n\n{findings}\n\n"
            f"## Risk rationale\n\nTier {facts['risk_tier']} / {facts['escalation_type']}. "
            f"Triggers: {', '.join(facts['triggers']) or 'pipeline uncertainty'}.\n\n"
            f"## Recommended next action\n\n{facts['owner_team']} to make first contact within "
            f"{facts['sla_hours']} hours and confirm the factual position before responding on "
            "substance. Nothing beyond the acknowledgement has been sent.\n\n"
            "_This brief was generated by the deterministic fallback because language generation "
            "failed; the facts above come from the case record._"
        )
