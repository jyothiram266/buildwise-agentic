"""Blocker digest ordering and impact statements (FR-CTR-3).

The digest's value is its ordering, so that is what gets asserted. Pure functions
only here; the connector-backed assembly is covered in the integration suite.
"""

from __future__ import annotations

from datetime import date

from governance.digest import STALE_BLOCKER_DAYS, DigestEntry, _headline, _impact


def entry(severity: str, age: int, blocker_id: str = "BLK-1", slipping=None) -> DigestEntry:
    return DigestEntry(
        blocker_id=blocker_id,
        category="material_shortage",
        severity=severity,
        description="cement stock exhausted",
        raised_on=date(2026, 8, 1),
        age_days=age,
        work_package_id="WP-AUR-B-STR",
        vendor_id="VEN-CEM-01",
        impacted_milestone_names=["Tower B · Slab 7"],
        slipping_milestones=slipping or [],
        stale=age >= STALE_BLOCKER_DAYS,
    )


def test_severity_outranks_age() -> None:
    ordered = sorted([entry("medium", 30), entry("critical", 1)], key=lambda e: e.sort_key)
    assert ordered[0].severity == "critical"


def test_age_breaks_ties_within_a_severity() -> None:
    ordered = sorted(
        [entry("high", 2, "BLK-new"), entry("high", 21, "BLK-old")], key=lambda e: e.sort_key
    )
    assert ordered[0].blocker_id == "BLK-old"


def test_stale_flag_uses_the_declared_threshold() -> None:
    assert entry("low", STALE_BLOCKER_DAYS - 1).stale is False
    assert entry("low", STALE_BLOCKER_DAYS).stale is True


def test_impact_statement_does_not_predict_a_new_date() -> None:
    """FR-CTR-4 in spirit: an impact statement is not a revised commitment."""
    statement = _impact("material_shortage", ["Tower B · Slab 7"], ["Tower B · Slab 7"], 9)
    assert "Slab 7" in statement
    assert not any(token in statement for token in ("2026-", "2027-", "will complete on"))


def test_unlinked_blocker_says_so_rather_than_guessing() -> None:
    statement = _impact("manpower", [], [], 4)
    assert "unassessed" in statement


def test_slipping_and_recoverable_read_differently() -> None:
    slipping = _impact("weather", ["A · Slab 3"], ["A · Slab 3"], 5)
    recoverable = _impact("weather", ["A · Slab 3"], [], 5)
    assert "now, not forecast" in slipping
    assert "recoverable" in recoverable


def test_headline_is_explicit_when_nothing_is_open() -> None:
    assert "nothing open" in _headline("Aurora Heights", [])


def test_headline_calls_out_stale_blockers() -> None:
    headline = _headline("Aurora Heights", [entry("high", 30)])
    assert "need a decision" in headline
