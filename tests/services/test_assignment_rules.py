"""Unit tests for derived overdue and assignment ordering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.assignment_rules import assignment_sort_key, is_assignment_overdue
from app.db.enums import AssignmentPriority, AssignmentStatus


def test_overdue_pending_past_due() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    assert is_assignment_overdue(past, AssignmentStatus.PENDING.value) is True


def test_overdue_in_progress_past_due() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    assert is_assignment_overdue(past, AssignmentStatus.IN_PROGRESS.value) is True


def test_overdue_completed_past_due_is_false() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    assert is_assignment_overdue(past, AssignmentStatus.COMPLETED.value) is False


def test_overdue_cancelled_past_due_is_false() -> None:
    past = datetime.now(UTC) - timedelta(days=1)
    assert is_assignment_overdue(past, AssignmentStatus.CANCELLED.value) is False


def test_overdue_future_deadline_is_false() -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    assert is_assignment_overdue(future, AssignmentStatus.PENDING.value) is False


def test_overdue_null_deadline_is_false() -> None:
    assert is_assignment_overdue(None, AssignmentStatus.PENDING.value) is False


def test_ordering_critical_before_important_before_normal() -> None:
    now = datetime.now(UTC)
    critical = assignment_sort_key(
        priority=AssignmentPriority.CRITICAL.value,
        due_at=None,
        status=AssignmentStatus.PENDING.value,
        assigned_at=now,
    )
    important = assignment_sort_key(
        priority=AssignmentPriority.IMPORTANT.value,
        due_at=now,
        status=AssignmentStatus.IN_PROGRESS.value,
        assigned_at=now,
    )
    normal = assignment_sort_key(
        priority=AssignmentPriority.NORMAL.value,
        due_at=now,
        status=AssignmentStatus.IN_PROGRESS.value,
        assigned_at=now,
    )
    assert critical < important < normal


def test_ordering_deadline_before_none_within_priority() -> None:
    now = datetime.now(UTC)
    with_due = assignment_sort_key(
        priority=AssignmentPriority.NORMAL.value,
        due_at=now + timedelta(days=3),
        status=AssignmentStatus.PENDING.value,
        assigned_at=now,
    )
    without_due = assignment_sort_key(
        priority=AssignmentPriority.NORMAL.value,
        due_at=None,
        status=AssignmentStatus.PENDING.value,
        assigned_at=now,
    )
    assert with_due < without_due


def test_ordering_nearest_deadline_first() -> None:
    now = datetime.now(UTC)
    nearer = assignment_sort_key(
        priority=AssignmentPriority.IMPORTANT.value,
        due_at=now + timedelta(days=1),
        status=AssignmentStatus.PENDING.value,
        assigned_at=now,
    )
    later = assignment_sort_key(
        priority=AssignmentPriority.IMPORTANT.value,
        due_at=now + timedelta(days=10),
        status=AssignmentStatus.PENDING.value,
        assigned_at=now,
    )
    assert nearer < later


def test_ordering_in_progress_before_pending_when_equal() -> None:
    now = datetime.now(UTC)
    due = now + timedelta(days=2)
    in_progress = assignment_sort_key(
        priority=AssignmentPriority.NORMAL.value,
        due_at=due,
        status=AssignmentStatus.IN_PROGRESS.value,
        assigned_at=now,
    )
    pending = assignment_sort_key(
        priority=AssignmentPriority.NORMAL.value,
        due_at=due,
        status=AssignmentStatus.PENDING.value,
        assigned_at=now,
    )
    assert in_progress < pending
