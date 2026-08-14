"""Risk tiering. Pure functions, zero model calls, zero I/O.

This is the most safety-critical module in the system and the least clever. Every
input is already-computed data; every output is a tier and a reason. That is what
makes it testable to the standard the PRD asks for (escalation recall ≥95%), and
what makes an auditor able to check a decision by reading a table rather than
inspecting a prompt.

Rules, in order of precedence:

1. A tier-3 trigger phrase in the actor's own words wins outright.
2. Safety-critical maintenance is tier 3 regardless of category confidence.
3. An internal-only finding heading for an external audience is at least tier 2.
4. Confidence below threshold anywhere in the pipeline is at least tier 2.
5. Missing data, source conflict, or a pipeline error is at least tier 2.
6. Ambiguity resolves upward, never downward.

`assess()` returns the tier, the escalation type, the owning team, the SLA and the
specific trigger that fired — so the escalation brief quotes the policy rather than
paraphrasing it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.enums import (
    EXTERNAL_ROLES,
    EscalationType,
    Intent,
    RiskTier,
    Role,
)
from core.models import AgentFinding, Classification
from governance.policy_registry import get_registry
from governance.severity import detect_safety_critical

#: Intents whose *content* is inherently a commitment risk when the audience is
#: external, even with high confidence and clean data.
COMMITMENT_SENSITIVE_INTENTS = {Intent.COMPLAINT_ESCALATION, Intent.PAYMENT}


@dataclass
class RiskAssessment:
    tier: RiskTier
    escalation_type: EscalationType | None = None
    owner_team: str | None = None
    sla_hours: int | None = None
    triggers: list[str] = field(default_factory=list)
    rationale: str = ""
    policy_version: str = "unversioned"
    gaps: list[str] = field(default_factory=list)

    @property
    def requires_human(self) -> bool:
        return int(self.tier) >= 2

    @property
    def acknowledgement_only(self) -> bool:
        """Tier 3: acknowledge receipt, escalate, say nothing on substance."""
        return self.tier == RiskTier.ESCALATE_ONLY


def _matrix() -> dict:
    return get_registry().policy("escalation_matrix")


def match_triggers(text: str) -> list[tuple[EscalationType, dict, list[str]]]:
    """Every escalation type whose trigger phrases appear in the text.

    All matches are returned rather than the first, because a message can be both a
    refund demand and a media threat, and the brief should name both. Ordering is
    by declared tier then by SLA, so the most urgent owner is first.
    """
    low = f" {text.lower()} "
    matches: list[tuple[EscalationType, dict, list[str]]] = []
    for name, spec in _matrix().get("types", {}).items():
        hits = [phrase for phrase in spec.get("triggers", []) if phrase in low]
        if hits:
            try:
                matches.append((EscalationType(name), spec, hits))
            except ValueError:  # pragma: no cover - guarded by policy validation
                continue
    matches.sort(key=lambda item: (-int(item[1].get("tier", 0)), int(item[1].get("sla_hours", 999))))
    return matches


def _from_type(
    escalation_type: EscalationType, spec: dict, triggers: list[str], rationale: str, gaps: list[str]
) -> RiskAssessment:
    return RiskAssessment(
        tier=RiskTier(int(spec.get("tier", 2))),
        escalation_type=escalation_type,
        owner_team=str(spec.get("owner_team", "customer_relations")),
        sla_hours=int(spec.get("sla_hours", 24)),
        triggers=triggers,
        rationale=rationale,
        policy_version=str(_matrix().get("version", "unversioned")),
        gaps=gaps,
    )


def spec_for(escalation_type: EscalationType) -> dict:
    return _matrix().get("types", {}).get(escalation_type.value, {})


def assess(
    *,
    text: str,
    role: Role,
    classification: Classification | None,
    findings: list[AgentFinding],
    confidence_threshold: float = 0.70,
    prior_contacts: int = 0,
    degraded: bool = False,
) -> RiskAssessment:
    """Assign the risk tier for a case. Deterministic given its inputs."""
    version = str(_matrix().get("version", "unversioned"))
    gaps = _gaps(findings)
    external = role in EXTERNAL_ROLES

    # --- Rule 1: an explicit tier-3 trigger in the actor's own words ---------
    matches = match_triggers(text)
    for escalation_type, spec, hits in matches:
        if int(spec.get("tier", 0)) >= 3:
            return _from_type(
                escalation_type,
                spec,
                hits,
                f"Tier 3 forced by escalation type {escalation_type.value}: {spec.get('label')}. "
                "Only an acknowledgement is sent; substance is handled by the owning team.",
                gaps,
            )

    # --- Rule 2: safety-critical maintenance --------------------------------
    #
    # Checked against the raw text first, then against the findings. Relying on the
    # finding alone was a real gap: if classification was uncertain the maintenance
    # agent never ran, so there was no finding to carry the flag, and a gas-leak
    # report was tiered on confidence instead of on hazard. Reading the text here
    # makes the hazard path independent of every model decision above it.
    if hazard := detect_safety_critical(text):
        name, spec, hits = hazard
        escalation_spec = spec_for(EscalationType.SAFETY_INCIDENT) or {
            "owner_team": spec.get("on_call", "safety_ehs"), "sla_hours": 2, "tier": 3
        }
        return _from_type(
            EscalationType.SAFETY_INCIDENT,
            escalation_spec,
            hits,
            f"Tier 3 forced by a safety-critical phrase in the request itself "
            f"({spec.get('label')}, matched on {', '.join(hits)}). This is independent of "
            "classification confidence and of whether any specialist agent ran.",
            gaps,
        )

    for finding in findings:
        if finding.structured.get("safety_critical"):
            signal = str(finding.structured.get("safety_signal") or "safety-critical signal")
            spec = spec_for(EscalationType.SAFETY_INCIDENT)
            return _from_type(
                EscalationType.SAFETY_INCIDENT,
                spec or {"owner_team": "safety_ehs", "sla_hours": 2, "tier": 3},
                [signal],
                f"Tier 3 forced by a safety-critical maintenance signal ({signal}). "
                "This is independent of model confidence.",
                gaps,
            )

    # --- Rule 3: internal content heading for an external audience ----------
    if external and any(f.internal_only for f in findings):
        agents = ", ".join(f.agent for f in findings if f.internal_only)
        return RiskAssessment(
            tier=RiskTier.DRAFT_APPROVAL,
            escalation_type=None,
            owner_team=None,
            sla_hours=None,
            triggers=[f"internal_only finding from {agents}"],
            rationale=(
                f"At least tier 2: findings from {agents} are internal-only and the audience is "
                f"external ({role.value}), so a human confirms what is disclosed."
            ),
            policy_version=version,
            gaps=gaps,
        )

    # --- Rule 4: pipeline confidence ---------------------------------------
    confidences = [f.confidence for f in findings if f.status == "ok"]
    if classification:
        confidences.append(classification.confidence)
    weakest = min(confidences) if confidences else 0.0
    if weakest < confidence_threshold:
        spec = spec_for(EscalationType.LOW_CONFIDENCE)
        return _from_type(
            EscalationType.LOW_CONFIDENCE,
            spec or {"owner_team": "customer_relations", "sla_hours": 12, "tier": 2},
            [f"confidence {weakest:.2f} below threshold {confidence_threshold:.2f}"],
            f"At least tier 2: the weakest confidence in the pipeline is {weakest:.2f}, below the "
            f"{confidence_threshold:.2f} threshold. Uncertainty is routed, not hidden.",
            gaps,
        )

    # --- Rule 5: data problems ---------------------------------------------
    if any(f.status == "conflict" for f in findings):
        spec = spec_for(EscalationType.SOURCE_CONFLICT)
        return _from_type(
            EscalationType.SOURCE_CONFLICT,
            spec or {"owner_team": "knowledge_ops", "sla_hours": 12, "tier": 2},
            ["conflicting approved sources"],
            "At least tier 2: two approved sources disagree. Picking one silently would make the "
            "system's confidence unearned.",
            gaps,
        )
    if gaps or degraded:
        spec = spec_for(EscalationType.MISSING_DATA)
        return _from_type(
            EscalationType.MISSING_DATA,
            spec or {"owner_team": "customer_relations", "sla_hours": 12, "tier": 2},
            gaps or ["pipeline degraded"],
            "At least tier 2: required data was unavailable or a component degraded, so the answer "
            "is incomplete by construction.",
            gaps,
        )

    # --- Rule 6: remaining tier-2 triggers and repeated contact ------------
    for escalation_type, spec, hits in matches:
        if int(spec.get("tier", 0)) == 2:
            return _from_type(
                escalation_type,
                spec,
                hits,
                f"Tier 2 from escalation type {escalation_type.value}: {spec.get('label')}.",
                gaps,
            )
    if prior_contacts >= 2:
        spec = spec_for(EscalationType.REPEATED_CONTACT)
        return _from_type(
            EscalationType.REPEATED_CONTACT,
            spec or {"owner_team": "customer_relations", "sla_hours": 12, "tier": 2},
            [f"{prior_contacts} prior contacts in the recent window"],
            "Tier 2: the actor has contacted us repeatedly, which is a service failure signal "
            "regardless of how well this particular answer reads.",
            gaps,
        )

    # --- Notify-only and fully automatic paths ------------------------------
    if classification and classification.intent in COMMITMENT_SENSITIVE_INTENTS and external:
        return RiskAssessment(
            tier=RiskTier.AUTO_NOTIFY,
            triggers=[f"intent {classification.intent.value} with an external audience"],
            rationale=(
                "Tier 1: answered automatically, with the owning team notified because the topic is "
                "commercially sensitive even when the answer is well grounded."
            ),
            policy_version=version,
            gaps=gaps,
        )

    return RiskAssessment(
        tier=RiskTier.AUTO,
        triggers=[],
        rationale=(
            "Tier 0: informational request, grounded findings, confidence above threshold, no "
            "escalation trigger and no internal content for an external audience."
        ),
        policy_version=version,
        gaps=gaps,
    )


def _gaps(findings: list[AgentFinding]) -> list[str]:
    out = []
    for finding in findings:
        if finding.status == "insufficient_data":
            out.append(f"{finding.agent}: insufficient data")
        elif finding.status == "error":
            out.append(f"{finding.agent}: error")
    return out
