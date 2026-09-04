"""Phase 9G reminder policy: windows, frequency, reduced, spacing."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from app.services.notification_settings import NotificationSettings
from app.services.reminder_policy import (
    SLOT_1,
    SLOT_2,
    decide_automated_slot,
    in_notification_window,
    manual_cooldown_active,
    manual_remind_blocked,
)


def _settings(**kwargs) -> NotificationSettings:
    return NotificationSettings(**kwargs)


def test_inside_window_slot_1_at_morning() -> None:
    now = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    decision = decide_automated_slot(
        now=now,
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="normal",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    assert decision.eligible is True
    assert decision.slot == SLOT_1


def test_before_and_after_window_not_eligible() -> None:
    settings = _settings()
    early = decide_automated_slot(
        now=datetime(2026, 9, 4, 7, 0, tzinfo=UTC),
        timezone_name="UTC",
        settings=settings,
        assignment_status="pending",
        priority="normal",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    late = decide_automated_slot(
        now=datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
        timezone_name="UTC",
        settings=settings,
        assignment_status="in_progress",
        priority="important",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    assert early.eligible is False
    assert early.reason == "outside_window"
    assert late.eligible is False


def test_quiet_hours_win() -> None:
    settings = _settings(
        quiet_hours_start=time(12, 0),
        quiet_hours_end=time(13, 0),
    )
    assert in_notification_window(time(12, 30), settings) is False
    assert in_notification_window(time(11, 0), settings) is True
    decision = decide_automated_slot(
        now=datetime(2026, 9, 4, 12, 30, tzinfo=UTC),
        timezone_name="UTC",
        settings=settings,
        assignment_status="pending",
        priority="critical",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    assert decision.eligible is False


def test_timezone_conversion_moscow() -> None:
    # 07:00 UTC = 10:00 Europe/Moscow, inside 09:00-18:00.
    decision = decide_automated_slot(
        now=datetime(2026, 9, 4, 7, 0, tzinfo=UTC),
        timezone_name="Europe/Moscow",
        settings=_settings(),
        assignment_status="pending",
        priority="normal",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    assert decision.eligible is True
    afternoon = decide_automated_slot(
        now=datetime(2026, 9, 4, 11, 0, tzinfo=UTC),
        timezone_name="Europe/Moscow",
        settings=_settings(),
        assignment_status="pending",
        priority="important",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    assert afternoon.eligible is True
    assert afternoon.slot in {SLOT_1, SLOT_2}


def test_normal_no_slot_2() -> None:
    now = datetime(2026, 9, 4, 16, 0, tzinfo=UTC)
    decision = decide_automated_slot(
        now=now,
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="normal",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=None,
        sent_slots_today={SLOT_1},
    )
    assert decision.eligible is False


def test_important_slot_2_after_spacing() -> None:
    now = datetime(2026, 9, 4, 16, 0, tzinfo=UTC)
    too_soon = decide_automated_slot(
        now=now,
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="important",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=now - timedelta(hours=1),
        sent_slots_today={SLOT_1},
    )
    ready = decide_automated_slot(
        now=now,
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="critical",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=now - timedelta(hours=4),
        sent_slots_today={SLOT_1},
    )
    assert too_soon.eligible is False
    assert too_soon.reason == "spacing"
    assert ready.eligible is True
    assert ready.slot == SLOT_2


def test_reduced_and_disabled_and_ack() -> None:
    now = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    today = now.date()
    disabled = decide_automated_slot(
        now=now,
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="critical",
        mode="disabled",
        acknowledged_until_date=None,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    acked = decide_automated_slot(
        now=now,
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="normal",
        mode="default",
        acknowledged_until_date=today,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    next_day = decide_automated_slot(
        now=now + timedelta(days=1),
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="normal",
        mode="default",
        acknowledged_until_date=today,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    reduced_important = decide_automated_slot(
        now=datetime(2026, 9, 4, 16, 0, tzinfo=UTC),
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="important",
        mode="reduced",
        acknowledged_until_date=None,
        last_automated_at=now,
        sent_slots_today={SLOT_1},
    )
    reduced_normal = decide_automated_slot(
        now=now + timedelta(days=1),
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="normal",
        mode="reduced",
        acknowledged_until_date=None,
        last_automated_at=now,
        sent_slots_today=set(),
    )
    reduced_normal_ready = decide_automated_slot(
        now=now + timedelta(days=2),
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="pending",
        priority="normal",
        mode="reduced",
        acknowledged_until_date=None,
        last_automated_at=now,
        sent_slots_today=set(),
    )
    assert disabled.eligible is False
    assert acked.eligible is False
    assert next_day.eligible is True
    assert reduced_important.eligible is False
    assert reduced_normal.eligible is False
    assert reduced_normal_ready.eligible is True


def test_closed_assignment_and_manual_cooldown() -> None:
    now = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    done = decide_automated_slot(
        now=now,
        timezone_name="UTC",
        settings=_settings(),
        assignment_status="completed",
        priority="normal",
        mode="default",
        acknowledged_until_date=None,
        last_automated_at=None,
        sent_slots_today=set(),
    )
    assert done.eligible is False
    assert manual_cooldown_active(now=now, last_manual_at=now - timedelta(minutes=3))
    assert not manual_cooldown_active(
        now=now, last_manual_at=now - timedelta(minutes=11)
    )
    assert manual_remind_blocked("disabled") is True
    assert manual_remind_blocked("default") is False
    assert manual_remind_blocked("reduced") is False
