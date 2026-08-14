"""Daily blocker digest per project (PRD FR-CTR-3).

A project manager does not want twelve contractor notifications; they want one
ordered list each morning of what is blocking their site and which milestones it
touches. That is a different artefact from a case response, so it lives here rather
than inside an agent: no request triggers it, and nothing about it is
conversational.

Two decisions worth stating:

* **The digest is assembled in code, not generated.** Ordering, impact and ageing
  are arithmetic over connector data. A model rewriting this list would add nothing
  and could reorder it, and the ordering is the value.
* **Internal by construction.** Every digest carries vendor names, disputes and
  cost-relevant detail, so it is never addressable to an external role. The route
  that serves it is restricted to internal roles and the payload is marked.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from api.config import get_logger
from connectors import registry
from connectors.project_mgmt import BlockerQuery, MilestoneQuery
from core.models import AccessScope
from db import pool
from governance import audit

log = get_logger(__name__)

#: Ordering weight per severity. Critical blockers sort above everything, then
#: ageing acts as the tie-breaker, because a medium blocker open for three weeks is
#: a worse management failure than a high one raised this morning.
SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}

#: Blockers older than this are called out separately: something that has been open
#: this long is not a site problem any more, it is an escalation nobody made.
STALE_BLOCKER_DAYS = 14


@dataclass
class DigestEntry:
    blocker_id: str
    category: str
    severity: str
    description: str
    raised_on: date
    age_days: int
    work_package_id: str | None
    vendor_id: str | None
    impacted_milestones: list[str] = field(default_factory=list)
    impacted_milestone_names: list[str] = field(default_factory=list)
    slipping_milestones: list[str] = field(default_factory=list)
    impact_statement: str = ""
    stale: bool = False

    @property
    def sort_key(self) -> tuple[int, int]:
        return (-SEVERITY_RANK.get(self.severity, 0), -self.age_days)

    def to_dict(self) -> dict[str, Any]:
        return {
            "blocker_id": self.blocker_id,
            "category": self.category,
            "severity": self.severity,
            "description": self.description,
            "raised_on": self.raised_on.isoformat(),
            "age_days": self.age_days,
            "work_package_id": self.work_package_id,
            "vendor_id": self.vendor_id,
            "impacted_milestones": self.impacted_milestones,
            "impacted_milestone_names": self.impacted_milestone_names,
            "slipping_milestones": self.slipping_milestones,
            "impact_statement": self.impact_statement,
            "stale": self.stale,
        }


async def build(
    project_id: str, scope: AccessScope, today: date | None = None
) -> dict[str, Any]:
    """Assemble the digest for one project.

    Reads through the connectors with the caller's scope, so a manager restricted to
    one project cannot produce a digest for another.
    """
    today = today or date.today()

    blockers = await registry.project_mgmt().query_blockers(
        BlockerQuery(project_id=project_id, open_only=True), scope
    )
    milestones = await registry.project_mgmt().query_milestones(
        MilestoneQuery(project_id=project_id), scope
    )

    # Milestone lookup so the digest can name what is affected rather than printing
    # ids a manager would have to resolve themselves.
    by_id: dict[str, Any] = {}
    for tower in milestones.towers:
        for milestone in tower.milestones:
            by_id[milestone.milestone_id] = (tower, milestone)

    entries: list[DigestEntry] = []
    for blocker in blockers.blockers:
        age = (today - blocker.raised_on).days
        names: list[str] = []
        slipping: list[str] = []
        for milestone_id in blocker.impacted_milestones:
            pair = by_id.get(milestone_id)
            if not pair:
                continue
            tower, milestone = pair
            names.append(f"{tower.tower_name} · {milestone.name}")
            late = milestone.actual_date is None and milestone.planned_date < today
            if late or milestone.status == "delayed":
                slipping.append(f"{tower.tower_name} · {milestone.name}")

        entries.append(
            DigestEntry(
                blocker_id=blocker.blocker_id,
                category=blocker.category,
                severity=blocker.severity,
                description=blocker.description[:400],
                raised_on=blocker.raised_on,
                age_days=age,
                work_package_id=blocker.work_package_id,
                vendor_id=blocker.vendor_id,
                impacted_milestones=list(blocker.impacted_milestones),
                impacted_milestone_names=names,
                slipping_milestones=slipping,
                impact_statement=_impact(blocker.category, names, slipping, age),
                stale=age >= STALE_BLOCKER_DAYS,
            )
        )

    entries.sort(key=lambda entry: entry.sort_key)

    project_name = milestones.towers[0].project_name if milestones.towers else project_id
    by_severity: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for entry in entries:
        by_severity[entry.severity] = by_severity.get(entry.severity, 0) + 1
        by_category[entry.category] = by_category.get(entry.category, 0) + 1

    return {
        "project_id": project_id,
        "project_name": project_name,
        "generated_for": today.isoformat(),
        "internal_only": True,
        "open_blockers": len(entries),
        "by_severity": by_severity,
        "by_category": by_category,
        "stale_count": sum(1 for entry in entries if entry.stale),
        "milestones_at_risk": sorted(
            {name for entry in entries for name in entry.slipping_milestones}
        ),
        "entries": [entry.to_dict() for entry in entries],
        "headline": _headline(project_name, entries),
    }


async def build_all(scope: AccessScope, today: date | None = None) -> list[dict[str, Any]]:
    """One digest per project the caller can see, worst first."""
    if scope.project_ids:
        project_ids = list(scope.project_ids)
    else:
        rows = await pool.fetch("SELECT project_id FROM projects ORDER BY project_id")
        project_ids = [row["project_id"] for row in rows]

    digests = [await build(project_id, scope, today) for project_id in project_ids]
    digests.sort(key=lambda d: (-d["open_blockers"], d["project_id"]))
    return digests


async def record_digest(project_id: str, digest: dict[str, Any], actor_id: str) -> None:
    """Log that the digest was produced, so delivery is auditable like anything else."""
    await audit.notify_team(
        "project_management",
        "daily_blocker_digest",
        f"{digest['project_name']}: {digest['open_blockers']} open blocker(s), "
        f"{digest['stale_count']} open beyond {STALE_BLOCKER_DAYS} days.",
        case_id=None,
    )
    log.info(
        "digest_generated",
        project_id=project_id,
        blockers=digest["open_blockers"],
        actor=actor_id,
    )


def _impact(category: str, names: list[str], slipping: list[str], age_days: int) -> str:
    """A plain impact sentence. Factual, and it does not predict a new date."""
    if not names:
        return (
            f"No milestone is linked to this blocker yet, so its schedule impact is unassessed "
            f"after {age_days} day(s). Linking it is the first action."
        )
    subject = names[0] if len(names) == 1 else f"{len(names)} milestones including {names[0]}"
    if slipping:
        return (
            f"{subject} already past planned date. Open {age_days} day(s); the schedule impact is "
            "being felt now, not forecast."
        )
    return (
        f"{subject} affected but not yet past planned date. Open {age_days} day(s) — still "
        "recoverable if cleared."
    )


def _headline(project_name: str, entries: list[DigestEntry]) -> str:
    if not entries:
        return f"{project_name}: nothing open. No blockers recorded against this project."
    worst = entries[0]
    stale = [entry for entry in entries if entry.stale]
    parts = [
        f"{project_name}: {len(entries)} open blocker(s). Worst is {worst.blocker_id} "
        f"({worst.severity}, {worst.category.replace('_', ' ')}), open {worst.age_days} day(s)."
    ]
    if stale:
        parts.append(
            f"{len(stale)} have been open beyond {STALE_BLOCKER_DAYS} days and need a decision "
            "rather than another update."
        )
    return " ".join(parts)
