"""Response agent and the disclosure gate.

Architecture Section 12 chose *separate generation per audience* over
generate-then-redact. The reasoning is worth restating because it drives the whole
file: a redaction step operates on text that already contains the secret, so every
bug in the redactor is a leak. Here the internal findings never enter the
customer-facing prompt at all, so there is nothing to redact.

The gate at the end is a second, independent check on the generated text — belt and
braces, and cheap. It scans for the specific things that must never appear in an
external message: an unapproved date, a vendor name, a cost figure, a commitment
verb. If it fires, the response is downgraded to a human draft rather than patched,
because a response that needed patching is a response nobody has checked.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from core.enums import EXTERNAL_ROLES, RiskTier, Role
from core.models import AgentFinding, ResponseDraft
from orchestration.state import CaseState

from agents.base import BaseAgent

PROMPT_BY_AUDIENCE: dict[Role, str] = {
    Role.PUBLIC_LEAD: "response_customer",
    Role.CUSTOMER: "response_customer",
    Role.RESIDENT: "response_customer",
    Role.BROKER: "response_broker",
    Role.CONTRACTOR: "response_contractor",
    Role.SALES_STAFF: "response_internal",
    Role.SITE_ENGINEER: "response_internal",
    Role.LEGAL_FINANCE: "response_internal",
    Role.MANAGER: "response_internal",
}

#: Phrases that would turn an informational answer into a commitment.
COMMITMENT_PHRASES = (
    "we guarantee", "i guarantee", "we promise", "i promise", "we assure you", "rest assured",
    "will definitely", "will certainly", "you will receive by", "we commit to", "guaranteed by",
    "we will refund", "we will waive", "we will approve", "we will compensate",
    "i can offer you a discount", "we can offer a discount",
)

#: Words that indicate internal content in an external message. FR-CON-3 names four
#: categories to suppress from customer-facing output, and all four are here:
#: contractor disputes, internal cost data, unconfirmed delay speculation, and
#: safety-incident detail.
INTERNAL_LEAKAGE_TERMS = (
    # contractor disputes
    "vendor", "subcontractor", "contractor dispute", "retention", "penalty clause",
    "liquidated damages", "ra bill", "contractor claim",
    # internal cost data
    "cost overrun", "margin", "cost per square", "procurement cost", "budget overrun",
    "internal cost", "rate contract",
    # unconfirmed delay speculation
    "may slip", "might slip", "could slip", "likely to slip", "expected to be delayed",
    "internally we", "we are anticipating", "not yet approved", "not approved",
    "unapproved", "pending approval from management", "subject to internal approval",
    # safety-incident detail (FR-CON-3): a customer is told a hazard is being handled,
    # never the injury detail, the person involved, or the incident narrative.
    "injured", "injury", "fatality", "accident on site", "fell from", "hospitalised",
    "incident report", "ehs report", "near miss", "casualty",
    # generic internal markers
    "internal only", "internally discussed", "internal note",
)

_MONEY = re.compile(r"(?:inr|rs\.?|₹)\s?[\d,]{4,}", re.I)


class ResponseOutput(BaseModel):
    text: str
    next_action: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class GateResult(BaseModel):
    """Outcome of the final disclosure check."""

    passed: bool
    violations: list[str] = []
    downgraded_to: str | None = None


def check_disclosure(
    text: str, audience: Role, findings: list[AgentFinding]
) -> GateResult:
    """Independent scan of generated text before it can be sent.

    Runs for external audiences only: an internal reader is cleared for cost,
    vendor and safety detail, and stripping it would make the answer useless to the
    person who needs it.
    """
    if audience not in EXTERNAL_ROLES:
        return GateResult(passed=True)

    low = text.lower()
    violations: list[str] = []

    for phrase in COMMITMENT_PHRASES:
        if phrase in low:
            violations.append(f"commitment language: '{phrase}'")

    if audience in {Role.CUSTOMER, Role.RESIDENT, Role.PUBLIC_LEAD, Role.BROKER}:
        for term in INTERNAL_LEAKAGE_TERMS:
            if term in low:
                violations.append(f"internal term in an external message: '{term}'")

    # An unapproved revised possession date must not appear in any form. The value
    # is compared against the findings rather than pattern-matched, so a date that
    # is legitimately approved does not trip the gate.
    for finding in findings:
        withheld = finding.structured.get("unapproved_revised_possession")
        if withheld and str(withheld) in text:
            violations.append("unapproved revised possession date present in the text")

    # A figure in an external message must trace to a structured field.
    quoted = {match.group(0) for match in _MONEY.finditer(text)}
    if quoted:
        grounded = " ".join(
            str(value) for finding in findings for value in finding.structured.values()
        )
        digits_available = set(re.findall(r"\d[\d,]{3,}", grounded))
        for amount in quoted:
            digits = re.sub(r"[^\d,]", "", amount)
            if digits and digits not in digits_available and digits.replace(",", "") not in {
                d.replace(",", "") for d in digits_available
            }:
                violations.append(f"amount '{amount}' does not trace to a structured field")

    return GateResult(
        passed=not violations,
        violations=violations,
        downgraded_to="draft_for_approval" if violations else None,
    )


class ResponseAgent(BaseAgent):
    name = "response"
    collections: list[str] = []

    async def _run(self, state: CaseState) -> AgentFinding:  # pragma: no cover - see compose
        raise NotImplementedError("call compose(state, tier)")

    async def compose(self, state: CaseState, tier: RiskTier) -> tuple[ResponseDraft, GateResult]:
        """Generate the response for this audience and run it through the gate."""
        audience = state.audience
        external = audience in EXTERNAL_ROLES

        # Tier 3: acknowledgement only. Composed in code, not generated — the one
        # message that must never say anything about substance is the one message
        # not worth handing to a model.
        if tier == RiskTier.ESCALATE_ONLY:
            escalation = state.finding("escalation")
            sla_hours = None
            if escalation:
                sla_hours = escalation.structured.get("decision", {}).get("sla_hours")
            draft = ResponseDraft(
                mode="acknowledgement_only",
                audience=audience,
                text=self._acknowledgement(sla_hours),
                citations=[],
                next_action="await_owner_team",
            )
            return draft, GateResult(passed=True)

        # Findings visible to this audience. For an external audience the internal
        # ones are removed here, before the prompt exists.
        visible = state.external_findings() if external else state.findings
        usable = [f for f in visible if f.status == "ok"]

        if not usable:
            gaps = [f.summary for f in visible if f.status != "ok"]
            draft = ResponseDraft(
                mode="refuse",
                audience=audience,
                text=self._refusal(gaps),
                citations=[],
                next_action="human_handoff",
            )
            return draft, GateResult(passed=True)

        prompt_id = PROMPT_BY_AUDIENCE.get(audience, "response_customer")
        payload = [
            {
                "agent": f.agent,
                "status": f.status,
                "summary": f.summary,
                "structured": f.structured,
                "confidence": f.confidence,
                "internal_only": f.internal_only,
                "citations": [c.model_dump(mode="json") for c in f.citations],
            }
            for f in visible
        ]
        output = await self.generate(
            state,
            {"findings": payload, "request": state.masked_input},
            ResponseOutput,
            prompt_id=prompt_id,
        )
        assert isinstance(output, ResponseOutput)

        gate = check_disclosure(output.text, audience, state.findings)
        citations = [c for f in usable for c in f.citations]

        mode = "draft_for_approval" if int(tier) >= 2 or not gate.passed else "auto_send"
        draft = ResponseDraft(
            mode=mode,  # type: ignore[arg-type]
            audience=audience,
            text=output.text,
            citations=self._dedupe(citations),
            next_action=output.next_action,
        )
        return draft, gate

    @staticmethod
    def _acknowledgement(sla_hours: int | None) -> str:
        window = f"within {sla_hours} hours" if sla_hours else "shortly"
        return (
            "Thank you for writing in. What you have raised needs a person from the responsible "
            f"team to look at it properly, and it has been passed to them — they will contact you "
            f"{window}.\n\n"
            "I am not going to give you a partial answer on this one, because getting it wrong "
            "would be worse than waiting for someone who can see the full position and act on it. "
            "Your case reference is with the team along with everything you have told us."
        )

    @staticmethod
    def _refusal(gaps: list[str]) -> str:
        detail = f" ({'; '.join(gaps[:2])})" if gaps else ""
        return (
            "I could not find a grounded answer to that in the records available to me"
            f"{detail}, so rather than guess I would rather get it to a person who can check "
            "properly. Would you like me to pass it to the team, or is there anything you can add "
            "that might help me look in the right place?"
        )

    @staticmethod
    def _dedupe(citations: list) -> list:
        seen: set[tuple] = set()
        out = []
        for citation in citations:
            key = (citation.source_id, citation.section)
            if key in seen:
                continue
            seen.add(key)
            out.append(citation)
        return out
