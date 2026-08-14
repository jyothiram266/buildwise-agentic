"""SLA arithmetic, including the ageing buckets the queue view sorts by."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.enums import Priority
from governance import sla


def test_priority_sla_comes_from_policy() -> None:
    assert sla.sla_hours_for_priority(Priority.P1) == 4
    assert sla.sla_hours_for_priority(Priority.P2) == 24
    assert sla.sla_hours_for_priority(Priority.P3) == 72
    assert sla.sla_hours_for_priority(Priority.P4) == 168


def test_response_hours_are_shorter_than_resolution() -> None:
    for priority in Priority:
        assert sla.response_hours_for_priority(priority) <= sla.sla_hours_for_priority(priority)


def test_due_at_is_simple_elapsed_time_by_default() -> None:
    """Safety work does not pause overnight, so business hours are opt-in."""
    start = datetime(2026, 8, 14, 17, 0, tzinfo=timezone.utc)
    assert sla.due_at(4, start) == start + timedelta(hours=4)


def test_business_hours_skip_the_night() -> None:
    start = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)  # 17:30 IST
    due = sla.due_at(4, start, business_hours_only=True)
    assert due > start + timedelta(hours=4)


def test_breach_is_detected() -> None:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    status = sla.status_for(now - timedelta(hours=2), now=now)
    assert status.breached is True
    assert status.remaining_minutes < 0


def test_ageing_buckets() -> None:
    assert sla.ageing_bucket(1) == "<4h"
    assert sla.ageing_bucket(6) == "4-24h"
    assert sla.ageing_bucket(40) == "1-3d"
    assert sla.ageing_bucket(100) == ">3d"


def test_age_status_measures_from_creation() -> None:
    now = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)
    created = now - timedelta(days=2)
    status = sla.age_status(created, now + timedelta(hours=1), now=now)
    assert status.ageing_bucket == "1-3d"
    assert status.breached is False
