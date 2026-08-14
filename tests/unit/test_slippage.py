"""Slippage is computed in code (PRD FR-CON-4), so it is tested like arithmetic."""

from __future__ import annotations

from datetime import date

from connectors.project_mgmt import MilestoneRecord, TowerProgress
from agents.construction import compute_slippage


def tower(**overrides) -> TowerProgress:
    base = dict(
        tower_id="TWR-AUR-B",
        tower_name="Tower B",
        project_id="PRJ-AUR",
        project_name="Aurora Heights",
        floors=18,
        status="under_construction",
        planned_possession=date(2026, 12, 31),
        milestones=[
            MilestoneRecord(
                milestone_id="MS-1", name="Excavation", seq=1,
                planned_date=date(2025, 1, 10), actual_date=date(2025, 1, 10),
                pct_complete=100.0, status="complete",
            ),
            MilestoneRecord(
                milestone_id="MS-2", name="Foundation", seq=2,
                planned_date=date(2025, 4, 1), actual_date=date(2025, 5, 1),
                pct_complete=100.0, status="complete",
            ),
            MilestoneRecord(
                milestone_id="MS-3", name="Slab 7", seq=3,
                planned_date=date(2026, 6, 1), actual_date=None,
                pct_complete=60.0, status="in_progress",
            ),
        ],
    )
    base.update(overrides)
    return TowerProgress(**base)


def test_percentage_is_the_milestone_average() -> None:
    result = compute_slippage(tower(), today=date(2026, 8, 14))
    assert result.milestones_total == 3
    assert result.milestones_complete == 2
    assert result.pct_complete == round((100 + 100 + 60) / 3, 1)


def test_completed_late_milestone_counts_as_slip() -> None:
    result = compute_slippage(tower(), today=date(2026, 8, 14))
    assert "Foundation" in result.slipped_milestones


def test_overdue_incomplete_milestone_counts_as_slip() -> None:
    result = compute_slippage(tower(), today=date(2026, 8, 14))
    # Slab 7 was planned for 1 June and is still open on 14 August.
    assert result.max_slip_days == 74
    assert result.slipped_milestones[0] == "Slab 7"


def test_flag_threshold_is_two_weeks() -> None:
    assert compute_slippage(tower(), today=date(2026, 8, 14)).flagged is True
    assert compute_slippage(tower(), today=date(2026, 6, 5)).flagged is False


def test_unapproved_revision_is_not_returned_as_the_possession_date() -> None:
    unapproved = tower(revised_possession=date(2027, 9, 30), revised_approved=False)
    assert compute_slippage(unapproved).approved_revised_possession is None

    approved = tower(revised_possession=date(2027, 3, 31), revised_approved=True)
    assert compute_slippage(approved).approved_revised_possession == date(2027, 3, 31)


def test_empty_register_does_not_divide_by_zero() -> None:
    result = compute_slippage(tower(milestones=[]))
    assert result.pct_complete == 0.0
    assert result.max_slip_days == 0
