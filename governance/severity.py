"""Deterministic maintenance policy: priority, routing, SLA, warranty.

Design rule #3 puts this in code, not in a prompt. The reason is testability: the
PRD requires 100% recall on safety-critical signals, and the only way to hold that
line is a function you can run 60 phrasings through in a unit test and diff the
output. A prompt that scores 98% on the same set is not a policy, it is a
tendency.

Everything here reads `governance/policies/severity_matrix.yaml` and
`warranty_policy.yaml`, so an ops change is a YAML edit plus a version bump, and
the published policy document is rendered from the same file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from core.enums import MaintenanceCategory, Priority
from governance.policy_registry import get_registry


@dataclass
class SeverityDecision:
    priority: Priority
    sla_hours: int
    response_hours: int
    assigned_team: str
    safety_critical: bool = False
    safety_class: str | None = None
    safety_label: str | None = None
    on_call_team: str | None = None
    matched_rule: str | None = None
    reason: str = ""
    matched_keywords: list[str] = field(default_factory=list)
    policy_version: str = "unversioned"

    def rationale(self) -> str:
        if self.safety_critical:
            return (
                f"Forced to {self.priority.value} by safety class {self.safety_class} "
                f"({self.safety_label}) on the phrase(s) {', '.join(self.matched_keywords)}. "
                f"On-call team {self.on_call_team} is engaged in parallel with the assigned team."
            )
        if self.matched_rule:
            return (
                f"{self.matched_rule} assigned {self.priority.value}: {self.reason} "
                f"(matched on {', '.join(self.matched_keywords)})."
            )
        return f"No rule matched; category default for {self.assigned_team} applied: {self.reason}"


def _matrix() -> dict:
    return get_registry().policy("severity_matrix")


@lru_cache(maxsize=4096)
def _pattern(phrase: str) -> re.Pattern[str]:
    """Word-boundary matcher.

    Substring matching is subtly wrong on this vocabulary: "sparking" contains
    "parking" and "lifted" contains "lift". A trailing "*" marks an intentional
    prefix match.
    """
    if phrase.endswith("*"):
        return re.compile(r"\b" + re.escape(phrase[:-1]), re.I)
    return re.compile(r"\b" + re.escape(phrase) + r"\b", re.I)


def _hit(text: str, phrase: str) -> bool:
    return _pattern(phrase).search(text) is not None


def detect_safety_critical(text: str) -> tuple[str, dict, list[str]] | None:
    """Return the first matching hazard class, its config, and the phrases hit.

    Substring matching on a curated phrase list, deliberately. Stemming or fuzzy
    matching would raise recall on paper and make the false-positive set impossible
    to reason about — and a false P1 costs an unnecessary emergency call-out, which
    is a cost the business can absorb, while a missed one is not.
    """
    low = f" {text.lower()} "
    for name, spec in _matrix().get("safety_critical", {}).items():
        hits = [kw for kw in spec.get("keywords", []) if _hit(low, kw)]
        # Pair matching catches natural word order that a phrase list misses.
        for pair in spec.get("co_occurrence", []):
            if all(_hit(low, term) for term in pair):
                hits.append(" + ".join(pair))
        if hits:
            return name, spec, hits
    return None


def assign_priority(category: MaintenanceCategory | str, text: str) -> SeverityDecision:
    """Deterministically assign priority, team and SLA for a complaint."""
    matrix = _matrix()
    version = str(matrix.get("version", "unversioned"))
    category_value = category.value if isinstance(category, MaintenanceCategory) else str(category)
    low = f" {text.lower()} "

    teams = matrix.get("teams", {})
    team = teams.get(category_value, "customer_relations")
    sla = matrix.get("sla_hours", {})
    response = matrix.get("response_hours", {})

    if hazard := detect_safety_critical(text):
        name, spec, hits = hazard
        return SeverityDecision(
            priority=Priority.P1,
            sla_hours=int(sla.get("P1", 4)),
            response_hours=int(response.get("P1", 1)),
            assigned_team=team,
            safety_critical=True,
            safety_class=name,
            safety_label=spec.get("label"),
            on_call_team=spec.get("on_call"),
            reason=f"Safety-critical: {spec.get('label')}",
            matched_keywords=hits,
            policy_version=version,
        )

    for rule in matrix.get("rules", []):
        categories = rule.get("categories") or []
        if categories and category_value not in categories:
            continue
        hits = [kw for kw in rule.get("any_keywords", []) if _hit(low, kw)]
        if not hits:
            continue
        priority = Priority(rule["priority"])
        return SeverityDecision(
            priority=priority,
            sla_hours=int(sla.get(priority.value, 72)),
            response_hours=int(response.get(priority.value, 12)),
            assigned_team=team,
            matched_rule=rule["id"],
            reason=rule.get("reason", ""),
            matched_keywords=hits,
            policy_version=version,
        )

    default = Priority(matrix.get("category_defaults", {}).get(category_value, "P3"))
    return SeverityDecision(
        priority=default,
        sla_hours=int(sla.get(default.value, 72)),
        response_hours=int(response.get(default.value, 12)),
        assigned_team=team,
        reason=f"category default for {category_value}",
        policy_version=version,
    )


# ---------------------------------------------------------------------------
# Warranty
# ---------------------------------------------------------------------------

#: Maintenance category to warranty component. A complaint category and a warranty
#: component are not the same taxonomy, and pretending they are produces confident
#: wrong answers about coverage.
CATEGORY_TO_COMPONENT: dict[str, str] = {
    "plumbing": "plumbing",
    "electrical": "electrical",
    "civil": "flooring",
    "lift": "lift",
    "water_supply": "plumbing",
    "common_area": "paint",
    "parking": "flooring",
    "security": "electrical",
    "warranty_claim": "structural",
}

STRUCTURAL_SIGNALS = ("crack", "beam", "column", "slab", "seepage", "waterproof", "leak from terrace")


@dataclass
class WarrantyIndication:
    component: str
    label: str
    months: int
    within_period: bool | None
    months_elapsed: int | None
    statement: str
    policy_version: str


def warranty_indication(
    category: MaintenanceCategory | str,
    text: str,
    possession_date: date | None,
    today: date | None = None,
) -> WarrantyIndication:
    """Indicate, never confirm, warranty coverage (PRD FR-MNT-5).

    The output is always hedged because the field position — resident alteration,
    misuse, an excluded cause — is not in any system this code can read. The
    customer gets a clear "appears to be within/outside", plus who confirms.
    """
    policy = get_registry().policy("warranty_policy")
    version = str(policy.get("version", "unversioned"))
    category_value = category.value if isinstance(category, MaintenanceCategory) else str(category)
    low = text.lower()

    component = CATEGORY_TO_COMPONENT.get(category_value, "flooring")
    if any(_hit(low, signal) for signal in STRUCTURAL_SIGNALS) and category_value in {
        "civil", "warranty_claim", "plumbing",
    }:
        component = "structural" if "crack" in low or "beam" in low or "column" in low else "waterproofing"

    spec = policy.get("components", {}).get(component, {"months": 12, "label": component})
    months = int(spec.get("months", 12))
    label = str(spec.get("label", component))

    if possession_date is None:
        return WarrantyIndication(
            component=component,
            label=label,
            months=months,
            within_period=None,
            months_elapsed=None,
            statement=(
                f"{label} carries a {months}-month coverage period from handover. Whether this "
                "particular case falls inside that period cannot be stated without the possession "
                "date on record, and the customer relations team will confirm."
            ),
            policy_version=version,
        )

    today = today or date.today()
    elapsed = (today.year - possession_date.year) * 12 + (today.month - possession_date.month)
    if today.day < possession_date.day:
        elapsed -= 1
    within = elapsed <= months

    statement = (
        f"{label} carries a {months}-month period from handover on {possession_date.isoformat()}; "
        f"{elapsed} month(s) have elapsed, so this appears to be "
        f"{'within' if within else 'outside'} the coverage period. This is an indication only — "
        "the site team confirms coverage after inspecting the cause, since resident alterations and "
        "wear and tear are excluded."
    )
    return WarrantyIndication(
        component=component,
        label=label,
        months=months,
        within_period=within,
        months_elapsed=elapsed,
        statement=statement,
        policy_version=version,
    )
