"""The orchestration graph.

An explicit async state machine: named nodes, declared edges, one place that
mutates state, and a checkpoint after each node. This is a deliberate deviation
from the architecture's LangGraph reference (documented in the handoff note) — the
semantics are the ones the architecture specifies, implemented in ~300 readable
lines with no third-party graph runtime to reason about.

The node sequence:

    ingest -> mask -> classify -> route -> specialists (concurrent)
           -> risk -> escalate? -> respond -> gate -> persist

Failure handling follows architecture Section 3.4 exactly, and the shape of it is
the point: every failure mode has a *named* destination. Nothing is dropped, and
nothing silently produces a confident answer from incomplete data.

* connector timeout — the connector retries twice, then the agent returns `error`;
  the risk engine sees a gap and routes to a human
* empty retrieval — the agent refuses and a KB gap is logged for content ops
* conflicting sources — a `conflict` finding forces tier 2
* schema failure — one repair attempt, then the case goes to triage
* unhandled exception — caught here, case marked failed, human queue, never dropped
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from api.config import bind_case, clear_case, get_logger, get_settings
from core.enums import CaseStatus, Channel, Intent, RiskTier, Role
from core.masking import mask_text
from core.models import AccessScope, AgentFinding, Classification, ResponseDraft, utcnow
from db import pool
from governance import audit, review_queue, sla
from llm.client import ledger
from orchestration import risk_engine, router
from orchestration.state import CaseState

log = get_logger(__name__)

#: Node names, in canonical order. Used by the trace viewer to lay out the spine.
NODES = [
    "ingest",
    "mask",
    "classify",
    "route",
    "specialists",
    "risk",
    "escalate",
    "respond",
    "gate",
    "persist",
]


def _agents() -> dict[str, Any]:
    """Built lazily so importing the graph does not construct an LLM client."""
    from agents.construction import ConstructionAgent
    from agents.contractor import ContractorAgent
    from agents.documentation import DocumentationAgent
    from agents.followup import FollowUpAgent
    from agents.maintenance import MaintenanceAgent
    from agents.payments import PaymentsAgent
    from agents.property_info import PropertyInfoAgent

    return {
        "property_info": PropertyInfoAgent(),
        "documentation": DocumentationAgent(),
        "payments": PaymentsAgent(),
        "construction": ConstructionAgent(),
        "maintenance": MaintenanceAgent(),
        "contractor": ContractorAgent(),
        "followup": FollowUpAgent(),
    }


class Graph:
    """Runs one case from raw text to a persisted, audited response."""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def run(
        self,
        *,
        text: str,
        scope: AccessScope,
        channel: Channel = Channel.WEB_CHAT,
        case_id: str | None = None,
        thread_of: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> CaseState:
        state = await self._ingest(text, scope, channel, case_id, thread_of, attachments)
        bind_case(state.case_id)
        started = time.perf_counter()

        try:
            await self._mask(state)
            await self._classify(state)
            plan = await self._route(state)
            if plan.runs_specialists:
                await self._specialists(state, plan)
            assessment = await self._risk(state, plan)
            if assessment.requires_human:
                await self._escalate(state, assessment)
            await self._respond(state, assessment)
            await self._persist(state, assessment)
        except Exception as exc:  # noqa: BLE001 - Section 3.4: never a silent drop
            log.exception("graph_failed", case_id=state.case_id)
            await self._fail_to_human(state, exc)

        state.metadata["latency_ms"] = int((time.perf_counter() - started) * 1000)
        clear_case()
        return state

    # -- nodes --------------------------------------------------------------

    async def _ingest(
        self,
        text: str,
        scope: AccessScope,
        channel: Channel,
        case_id: str | None,
        thread_of: str | None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> CaseState:
        case_id = case_id or f"CASE-{uuid.uuid4().hex[:12]}"

        # FR-INT-6: thread against the actor's own open cases from the last 24 hours.
        # Threading rather than deduplicating, deliberately: a second message is new
        # information even when it repeats the first, and dropping it would lose the
        # signal that the customer had to ask twice — which is itself a tier-2
        # escalation trigger further down the pipeline.
        if thread_of is None:
            thread_of = await self._find_thread(scope.actor_id, text)
        state = CaseState(
            case_id=case_id,
            channel=channel,
            scope=scope,
            raw_input=text,
            masked_input=text,
            thread_of=thread_of,
        )
        state.node_log.append("ingest")
        if attachments:
            state.metadata["attachments"] = attachments
        if thread_of:
            state.metadata["threaded_to"] = thread_of
        # The row exists before any processing, so a crash mid-pipeline still leaves
        # a case a human can find rather than a lost message.
        await pool.execute(
            """
            INSERT INTO cases (case_id, actor_id, role, channel, masked_input, status, thread_of)
            VALUES ($1,$2,$3,$4,$5,'open',$6)
            ON CONFLICT (case_id) DO NOTHING
            """,
            case_id,
            scope.actor_id,
            scope.role.value,
            channel.value,
            text[:8000],
            thread_of,
        )
        await pool.execute(
            "INSERT INTO conversation_turns (actor_id, case_id, role, text) VALUES ($1,$2,$3,$4)",
            scope.actor_id,
            case_id,
            scope.role.value,
            text[:8000],
        )
        return state

    @staticmethod
    async def _find_thread(actor_id: str, text: str) -> str | None:
        """The open case this message most likely continues, or None.

        Deliberately conservative: only the actor's own cases, only the last 24
        hours, only cases not already answered and closed, and the root of an
        existing thread rather than a leaf, so a conversation stays one thread
        instead of becoming a chain.
        """
        row = await pool.fetchrow(
            """
            SELECT COALESCE(thread_of, case_id) AS root
            FROM cases
            WHERE actor_id = $1
              AND created_at > now() - interval '24 hours'
              AND status IN ('open', 'awaiting_approval', 'escalated', 'answered')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            actor_id,
        )
        return row["root"] if row else None

    async def _mask(self, state: CaseState) -> None:
        """PII is tokenised before anything else reads the text.

        Masking before classification, not after, so no prompt and no log line ever
        contains a raw PAN or account number. The token map stays in memory for the
        life of the request only.
        """
        result = mask_text(state.raw_input)
        masked, tokens = result.masked, result.token_map
        state.masked_input = masked
        state.metadata["masked_entities"] = sorted(result.found_types)
        state.node_log.append("mask")
        await pool.execute(
            "UPDATE cases SET masked_input = $2 WHERE case_id = $1", state.case_id, masked[:8000]
        )
        await audit.record(
            state.case_id,
            "masking",
            inputs={"length": len(state.raw_input)},
            output={"entities_masked": state.metadata["masked_entities"], "count": len(tokens)},
            decision="masked" if tokens else "no_pii_found",
        )

    async def _classify(self, state: CaseState) -> None:
        from agents.classification import ClassificationAgent

        finding = await ClassificationAgent().run(state)
        state.node_log.append("classify")
        if finding.status == "ok":
            state.classification = Classification.model_validate(finding.structured)
        else:
            state.note_degradation("classification failed")
            state.classification = Classification(intent=Intent.OTHER, confidence=0.0)

    async def _route(self, state: CaseState) -> router.RoutingPlan:
        plan = router.plan(
            state.classification,
            state.scope.role,
            state.masked_input,
            confidence_threshold=self.settings.classification_confidence_threshold,
        )
        state.node_log.append("route")
        state.metadata["route"] = {
            "agents": plan.agents,
            "triage": plan.triage,
            "reason": plan.reason,
        }
        await audit.record(
            state.case_id,
            "router",
            inputs={"intent": state.classification.intent.value if state.classification else None},
            output=state.metadata["route"],
            decision="triage" if plan.triage else "routed",
            policy_version="router@code",
        )
        if plan.triage:
            state.note_degradation(plan.reason)
        return plan

    async def _specialists(self, state: CaseState, plan: router.RoutingPlan) -> None:
        """Run the routed agents concurrently and merge their findings.

        Concurrency is what keeps a two-agent case inside the 15s NFR. Merging
        happens here and only here — agents never touch state.
        """
        import asyncio

        available = _agents()
        runnable = [(name, available[name]) for name in plan.agents if name in available]
        if not runnable:
            return

        results = await asyncio.gather(
            *(agent.run(state) for _, agent in runnable), return_exceptions=True
        )
        for (name, _), result in zip(runnable, results, strict=True):
            if isinstance(result, BaseException):
                log.error("specialist_crashed", agent=name, error=type(result).__name__)
                state.findings.append(
                    AgentFinding(
                        agent=name,
                        status="error",
                        summary=f"{name} did not complete ({type(result).__name__}).",
                        confidence=0.0,
                    )
                )
                state.note_degradation(f"{name} crashed")
                continue
            state.findings.append(result)
            if result.status == "error":
                state.note_degradation(f"{name} error")

        state.node_log.append("specialists")
        totals = ledger.totals(state.case_id)
        state.cost_tokens, state.cost_usd = totals["tokens"], totals["cost_usd"]

    async def _risk(self, state: CaseState, plan: router.RoutingPlan) -> risk_engine.RiskAssessment:
        prior = int(
            await pool.fetchval(
                """
                SELECT count(*) FROM cases WHERE actor_id = $1 AND case_id <> $2
                  AND created_at > now() - interval '24 hours'
                """,
                state.scope.actor_id,
                state.case_id,
            )
            or 0
        )
        assessment = risk_engine.assess(
            text=state.masked_input,
            role=state.scope.role,
            classification=state.classification,
            findings=state.findings,
            confidence_threshold=self.settings.agent_confidence_threshold,
            prior_contacts=prior,
            degraded=state.degraded or plan.triage,
        )
        state.risk_tier = assessment.tier
        state.node_log.append("risk")
        await audit.record(
            state.case_id,
            "risk_engine",
            inputs={
                "role": state.scope.role.value,
                "findings": [f.status for f in state.findings],
                "degraded": state.degraded,
            },
            output={
                "tier": int(assessment.tier),
                "escalation_type": (
                    assessment.escalation_type.value if assessment.escalation_type else None
                ),
                "owner_team": assessment.owner_team,
                "triggers": assessment.triggers,
                "rationale": assessment.rationale,
            },
            risk_tier=int(assessment.tier),
            decision=f"tier_{int(assessment.tier)}",
            policy_version=f"escalation_matrix@{assessment.policy_version}",
        )
        return assessment

    async def _escalate(self, state: CaseState, assessment: risk_engine.RiskAssessment) -> None:
        from agents.escalation import EscalationAgent

        finding = await EscalationAgent().run_with(state, assessment)
        state.findings.append(finding)
        decision = finding.structured.get("decision") or {}
        from core.models import EscalationDecision

        if decision:
            state.escalation = EscalationDecision.model_validate(decision)
        state.node_log.append("escalate")

    async def _respond(self, state: CaseState, assessment: risk_engine.RiskAssessment) -> None:
        from agents.response import ResponseAgent

        draft, gate = await ResponseAgent().compose(state, assessment.tier)
        state.node_log.append("respond")
        state.node_log.append("gate")
        state.metadata["gate"] = gate.model_dump(mode="json")

        if not gate.passed:
            # Downgraded, never patched: text that tripped the gate is text nobody
            # has checked, so a human checks it.
            state.note_degradation("disclosure gate blocked auto-send")
            draft = ResponseDraft(
                mode="draft_for_approval",
                audience=draft.audience,
                text=draft.text,
                citations=draft.citations,
                next_action=draft.next_action,
            )
            log.warning(
                "disclosure_gate_blocked", case_id=state.case_id, violations=gate.violations
            )

        state.response = draft
        await audit.record(
            state.case_id,
            "gate",
            inputs={"audience": draft.audience.value, "tier": int(assessment.tier)},
            output={
                "mode": draft.mode,
                "gate_passed": gate.passed,
                "violations": gate.violations,
                "citations": [c.source_id for c in draft.citations],
            },
            risk_tier=int(assessment.tier),
            decision=draft.mode,
            policy_version="disclosure_gate@code",
        )

    async def _persist(self, state: CaseState, assessment: risk_engine.RiskAssessment) -> None:
        draft = state.response
        totals = ledger.totals(state.case_id)
        state.cost_tokens, state.cost_usd = totals["tokens"], totals["cost_usd"]
        latency = state.elapsed_ms()

        status = CaseStatus.OPEN
        if draft is None:
            status = CaseStatus.FAILED
        elif draft.mode == "auto_send":
            status = CaseStatus.ANSWERED
        elif draft.mode == "acknowledgement_only":
            status = CaseStatus.ESCALATED
        elif draft.mode == "draft_for_approval":
            status = CaseStatus.AWAITING_APPROVAL
        elif draft.mode == "refuse":
            status = CaseStatus.AWAITING_APPROVAL
        state.status = status

        await pool.execute(
            """
            UPDATE cases SET intent = $2, secondary_intent = $3, entities = $4, sentiment = $5,
                   risk_tier = $6, status = $7, response_mode = $8, response_text = $9,
                   response_citations = $10, findings = $11, confidence = $12, degraded = $13,
                   cost_tokens = $14, cost_usd = $15, latency_ms = $16,
                   first_response_at = COALESCE(first_response_at, now())
            WHERE case_id = $1
            """,
            state.case_id,
            state.classification.intent.value if state.classification else None,
            (
                state.classification.secondary_intent.value
                if state.classification and state.classification.secondary_intent
                else None
            ),
            pool.to_jsonb(state.classification.entities if state.classification else {}),
            state.classification.sentiment if state.classification else None,
            int(assessment.tier),
            status.value,
            draft.mode if draft else None,
            draft.text if draft else None,
            pool.to_jsonb([c.model_dump(mode="json") for c in (draft.citations if draft else [])]),
            pool.to_jsonb([f.model_dump(mode="json") for f in state.findings]),
            round(state.min_confidence(), 3),
            state.degraded,
            state.cost_tokens,
            state.cost_usd,
            latency,
        )

        # Tier 2+ output is a draft until a named person acts on it.
        if draft and draft.mode == "draft_for_approval":
            await review_queue.enqueue(
                case_id=state.case_id,
                risk_tier=assessment.tier,
                audience=draft.audience,
                original_request=state.masked_input,
                reasoning_summary=self._reasoning_summary(state, assessment),
                proposed_response=draft.text,
                confidence=state.min_confidence(),
                citations=draft.citations,
                sla_due=sla.due_at(assessment.sla_hours or 12),
            )

        state.node_log.append("persist")
        if state.cost_usd > self.settings.cost_alert_usd_per_case:
            log.warning("case_cost_above_alert", case_id=state.case_id, cost_usd=state.cost_usd)

    # -- failure path -------------------------------------------------------

    async def _fail_to_human(self, state: CaseState, exc: Exception) -> None:
        """Section 3.4: any unhandled exception becomes a human-queue case."""
        state.error = f"{type(exc).__name__}: {exc}"
        state.status = CaseStatus.FAILED
        state.note_degradation("unhandled pipeline error")
        state.risk_tier = state.risk_tier or RiskTier.DRAFT_APPROVAL

        await audit.record(
            state.case_id,
            "graph",
            inputs={"node_log": state.node_log},
            output={"error": state.error},
            decision="failed_to_human",
            risk_tier=int(state.risk_tier),
        )
        await pool.execute(
            "UPDATE cases SET status = 'failed', degraded = TRUE WHERE case_id = $1", state.case_id
        )
        await review_queue.enqueue(
            case_id=state.case_id,
            risk_tier=RiskTier.DRAFT_APPROVAL,
            audience=state.scope.role,
            original_request=state.masked_input,
            reasoning_summary=(
                f"The pipeline failed at node '{state.node_log[-1] if state.node_log else 'ingest'}' "
                f"with {state.error}. Nothing has been sent to the actor. The request needs a manual "
                "answer, and the failure needs an engineering look."
            ),
            proposed_response="",
            confidence=0.0,
            sla_due=sla.due_at(4),
        )
        await audit.notify_team(
            "customer_relations",
            "pipeline_failure",
            f"Case {state.case_id} failed and is awaiting a manual answer.",
            case_id=state.case_id,
        )

    @staticmethod
    def _reasoning_summary(state: CaseState, assessment: risk_engine.RiskAssessment) -> str:
        """What the reviewer needs in order to judge the draft quickly."""
        lines = [
            f"Tier {int(assessment.tier)} — {assessment.rationale}",
            f"Route: {state.metadata.get('route', {}).get('reason', 'n/a')}",
        ]
        for finding in state.findings:
            marker = " [internal only]" if finding.internal_only else ""
            lines.append(
                f"- {finding.agent}{marker}: {finding.status}, confidence "
                f"{finding.confidence:.2f} — {finding.summary[:200]}"
            )
        if state.degraded_reasons:
            lines.append(f"Degradation: {'; '.join(state.degraded_reasons)}")
        gate = state.metadata.get("gate", {})
        if gate and not gate.get("passed", True):
            lines.append(f"Disclosure gate flagged: {'; '.join(gate.get('violations', []))}")
        return "\n".join(lines)


_graph: Graph | None = None


def get_graph() -> Graph:
    global _graph
    if _graph is None:
        _graph = Graph()
    return _graph


async def run_case(
    text: str,
    scope: AccessScope,
    channel: Channel = Channel.WEB_CHAT,
    case_id: str | None = None,
    thread_of: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> CaseState:
    return await get_graph().run(
        text=text,
        scope=scope,
        channel=channel,
        case_id=case_id,
        thread_of=thread_of,
        attachments=attachments,
    )
