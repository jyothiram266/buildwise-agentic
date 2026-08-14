"""SLA arithmetic.

Kept in one module because an SLA that is computed in three places will disagree
with itself within a month, and the disagreement will surface as an argument
between two teams rather than as a bug report.

Business hours are supported but off by default: safety-critical work does not
pause at 6pm, and quietly applying office hours to a P1 is the kind of policy
detail that looks harmless in code and indefensible in an incident review.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Literal

from api.config import get_settings
from core.enums import Priority
from core.models import SLAStatus, utcnow
from governance.policy_registry import get_registry

IST = timezone(timedelta(hours=5, minutes=30))
Bucket = Literal["<4h", "4-24h", "1-3d", ">3d"]


def sla_hours_for_priority(priority: Priority | str) -> int:
    matrix = get_registry().policy("severity_matrix")
    key = priority.value if isinstance(priority, Priority) else str(priority)
    hours = matrix.get("sla_hours", {}).get(key)
    if hours is None:
        raise KeyError(f"severity matrix has no sla_hours entry for {key!r}")
    return int(hours)


def response_hours_for_priority(priority: Priority | str) -> int:
    matrix = get_registry().policy("severity_matrix")
    key = priority.value if isinstance(priority, Priority) else str(priority)
    return int(matrix.get("response_hours", {}).get(key, sla_hours_for_priority(key)))


def add_business_hours(start: datetime, hours: int) -> datetime:
    """Advance a clock through working hours only, in the configured local zone."""
    settings = get_settings()
    open_h, close_h = settings.business_hours_start, settings.business_hours_end
    span = close_h - open_h
    if span <= 0:
        raise ValueError("business_hours_end must be after business_hours_start")

    cursor = start.astimezone(IST)
    remaining = float(hours)

    while remaining > 0:
        if cursor.weekday() >= 6:  # Sunday off; Saturday is a working day on site
            cursor = datetime.combine(cursor.date() + timedelta(days=1), time(open_h), tzinfo=IST)
            continue
        day_open = cursor.replace(hour=open_h, minute=0, second=0, microsecond=0)
        day_close = cursor.replace(hour=close_h, minute=0, second=0, microsecond=0)
        if cursor < day_open:
            cursor = day_open
        if cursor >= day_close:
            cursor = datetime.combine(cursor.date() + timedelta(days=1), time(open_h), tzinfo=IST)
            continue
        available = (day_close - cursor).total_seconds() / 3600
        if remaining <= available:
            cursor += timedelta(hours=remaining)
            remaining = 0
        else:
            remaining -= available
            cursor = datetime.combine(cursor.date() + timedelta(days=1), time(open_h), tzinfo=IST)

    return cursor.astimezone(timezone.utc)


def due_at(hours: int, start: datetime | None = None, business_hours_only: bool = False) -> datetime:
    start = start or utcnow()
    if business_hours_only:
        return add_business_hours(start, hours)
    return start + timedelta(hours=hours)


def ageing_bucket(age_hours: float) -> Bucket:
    if age_hours < 4:
        return "<4h"
    if age_hours < 24:
        return "4-24h"
    if age_hours < 72:
        return "1-3d"
    return ">3d"


def status_for(
    due: datetime, now: datetime | None = None, business_hours_only: bool = False
) -> SLAStatus:
    now = now or utcnow()
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    remaining = (due - now).total_seconds() / 60
    # Age is measured from when the clock would have started, so a breached item
    # ages into the right bucket rather than sitting at "<4h" forever.
    elapsed_hours = max(0.0, -remaining / 60)
    return SLAStatus(
        due_at=due,
        remaining_minutes=int(remaining),
        breached=remaining < 0,
        ageing_bucket=ageing_bucket(elapsed_hours if remaining < 0 else 0.0),
        business_hours_only=business_hours_only,
    )


def age_status(created_at: datetime, due: datetime, now: datetime | None = None) -> SLAStatus:
    """Ageing measured from creation — what a queue view needs to sort by."""
    now = now or utcnow()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    age_hours = (now - created_at).total_seconds() / 3600
    remaining = (due - now).total_seconds() / 60
    return SLAStatus(
        due_at=due,
        remaining_minutes=int(remaining),
        breached=remaining < 0,
        ageing_bucket=ageing_bucket(age_hours),
    )
