"""Deterministic assignment reminder frequency and window rules.

Reduced policy:
- important/critical → 1 automated reminder per local day (slot 1 only)
- normal → 1 automated reminder every 2 local days (slot 1 only)

Default policy:
- normal → 1/day (slot 1)
- important/critical → up to 2/day (slot 1 then slot 2), with 3-hour spacing

Disabled mode blocks automated reminders and management Remind now.
HR/Admin cannot re-enable employee reminders.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from app.db.enums import AssignmentPriority, ReminderMode
from app.services.notification_settings import (
    NotificationSettings,
    resolve_timezone,
)

SLOT_1 = 1
SLOT_2 = 2
MIN_AUTOMATED_SPACING = timedelta(hours=3)
MANUAL_REMIND_COOLDOWN = timedelta(minutes=10)

_ACTIVE_STATUSES = frozenset({"pending", "in_progress"})
_ASSIGNMENT_SOURCE_TYPES = frozenset(
    {
        "assignment_initial",
        "assignment_reminder",
        "assignment_manual_reminder",
    }
)


@dataclass(frozen=True, slots=True)
class ReminderDecision:
    eligible: bool
    slot: int | None
    reason: str


def to_aware_utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def company_local(now: datetime, timezone_name: str) -> datetime:
    return to_aware_utc(now).astimezone(resolve_timezone(timezone_name))


def in_half_open_window(current: time, start: time, end: time) -> bool:
    """True when current is in [start, end). Overnight wrap is supported."""
    current = current.replace(second=0, microsecond=0)
    if start == end:
        return False
    if start < end:
        return start <= current < end
    return current >= start or current < end


def in_quiet_hours(
    current: time,
    settings: NotificationSettings,
) -> bool:
    if settings.quiet_hours_start is None or settings.quiet_hours_end is None:
        return False
    return in_half_open_window(
        current,
        settings.quiet_hours_start,
        settings.quiet_hours_end,
    )


def in_notification_window(
    current: time,
    settings: NotificationSettings,
) -> bool:
    if not in_half_open_window(current, settings.window_start, settings.window_end):
        return False
    return not in_quiet_hours(current, settings)


def window_midpoint(settings: NotificationSettings) -> time:
    start_m = settings.window_start.hour * 60 + settings.window_start.minute
    end_m = settings.window_end.hour * 60 + settings.window_end.minute
    mid = (start_m + end_m) // 2
    return time(mid // 60, mid % 60)


def open_slots(local_dt: datetime, settings: NotificationSettings) -> frozenset[int]:
    current = local_dt.timetz().replace(tzinfo=None)
    if not in_notification_window(current, settings):
        return frozenset()
    slots = {SLOT_1}
    if current >= window_midpoint(settings):
        slots.add(SLOT_2)
    return frozenset(slots)


def max_daily_slots(priority: str, mode: str) -> int:
    if mode == ReminderMode.DISABLED.value:
        return 0
    if mode == ReminderMode.REDUCED.value:
        return 1
    if priority in {
        AssignmentPriority.IMPORTANT.value,
        AssignmentPriority.CRITICAL.value,
    }:
        return 2
    return 1


def reduced_normal_blocks_today(
    *,
    last_automated_at: datetime | None,
    local_today,
    timezone_name: str,
) -> bool:
    """Normal+reduced: skip if last automated was yesterday or today."""
    if last_automated_at is None:
        return False
    last_local = company_local(last_automated_at, timezone_name).date()
    return last_local >= local_today - timedelta(days=1)


def reminder_source_key(assignment_id: UUID, local_date, slot: int) -> str:
    return f"assignment:{assignment_id}:reminder:{local_date.isoformat()}:{slot}"


def initial_source_key(assignment_id: UUID) -> str:
    return f"assignment:{assignment_id}:initial"


def manual_source_key(assignment_id: UUID, event_id: UUID) -> str:
    return f"assignment:{assignment_id}:manual:{event_id}"


def parse_assignment_id_from_source_key(source_key: str) -> UUID | None:
    parts = source_key.split(":")
    if len(parts) < 2 or parts[0] != "assignment":
        return None
    try:
        return UUID(parts[1])
    except ValueError:
        return None


def is_assignment_outbound_type(source_type: str) -> bool:
    return source_type in _ASSIGNMENT_SOURCE_TYPES


def decide_automated_slot(
    *,
    now: datetime,
    timezone_name: str,
    settings: NotificationSettings,
    assignment_status: str,
    priority: str,
    mode: str,
    acknowledged_until_date,
    last_automated_at: datetime | None,
    sent_slots_today: set[int],
) -> ReminderDecision:
    if assignment_status not in _ACTIVE_STATUSES:
        return ReminderDecision(False, None, "assignment_closed")
    if mode == ReminderMode.DISABLED.value:
        return ReminderDecision(False, None, "disabled")

    local_dt = company_local(now, timezone_name)
    local_today = local_dt.date()
    if acknowledged_until_date is not None and acknowledged_until_date >= local_today:
        return ReminderDecision(False, None, "acknowledged_today")
    if not in_notification_window(local_dt.timetz().replace(tzinfo=None), settings):
        return ReminderDecision(False, None, "outside_window")

    allowed = max_daily_slots(priority, mode)
    if allowed <= 0:
        return ReminderDecision(False, None, "no_slots")
    if (
        mode == ReminderMode.REDUCED.value
        and priority == AssignmentPriority.NORMAL.value
        and reduced_normal_blocks_today(
            last_automated_at=last_automated_at,
            local_today=local_today,
            timezone_name=timezone_name,
        )
    ):
        return ReminderDecision(False, None, "reduced_interval")

    available = open_slots(local_dt, settings)
    for slot in sorted(available):
        if slot > allowed:
            continue
        if slot in sent_slots_today:
            continue
        if last_automated_at is not None:
            last_utc = to_aware_utc(last_automated_at)
            if to_aware_utc(now) - last_utc < MIN_AUTOMATED_SPACING:
                return ReminderDecision(False, None, "spacing")
        return ReminderDecision(True, slot, "ok")
    return ReminderDecision(False, None, "slot_already_sent")


def manual_cooldown_active(
    *,
    now: datetime,
    last_manual_at: datetime | None,
) -> bool:
    if last_manual_at is None:
        return False
    return to_aware_utc(now) - to_aware_utc(last_manual_at) < MANUAL_REMIND_COOLDOWN


def manual_remind_blocked(mode: str) -> bool:
    """Employee disabled reminders: no automated scan and no management Remind now."""
    return mode == ReminderMode.DISABLED.value
