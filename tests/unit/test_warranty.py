"""Warranty indication is always hedged, and always says who confirms."""

from __future__ import annotations

from datetime import date

from core.enums import MaintenanceCategory
from governance import severity


def test_within_period_is_indicated_not_confirmed() -> None:
    result = severity.warranty_indication(
        MaintenanceCategory.PLUMBING,
        "the concealed pipe is leaking",
        possession_date=date(2026, 3, 1),
        today=date(2026, 8, 14),
    )
    assert result.within_period is True
    assert "indication only" in result.statement
    assert "confirm" in result.statement


def test_outside_period_is_stated_plainly() -> None:
    result = severity.warranty_indication(
        MaintenanceCategory.ELECTRICAL,
        "the socket has failed",
        possession_date=date(2023, 1, 1),
        today=date(2026, 8, 14),
    )
    assert result.within_period is False
    assert "outside" in result.statement


def test_missing_possession_date_does_not_guess() -> None:
    result = severity.warranty_indication(
        MaintenanceCategory.CIVIL, "tiles have lifted", possession_date=None
    )
    assert result.within_period is None
    assert result.months_elapsed is None
    assert "cannot be stated" in result.statement


def test_structural_language_maps_to_the_long_period() -> None:
    result = severity.warranty_indication(
        MaintenanceCategory.CIVIL,
        "there is a crack in the beam",
        possession_date=date(2024, 1, 1),
        today=date(2026, 8, 14),
    )
    assert result.component == "structural"
    assert result.months == 60
    assert result.within_period is True
