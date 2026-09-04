"""Assignment priority, overdue, and list-ordering rules.

Overdue is derived, never stored. Ordering is shared by repository SQL,
employee web, and Telegram lists.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.db.enums import AssignmentPriority, AssignmentStatus

PRIORITY_RANK: dict[str, int] = {
    AssignmentPriority.CRITICAL.value: 0,
    AssignmentPriority.IMPORTANT.value: 1,
    AssignmentPriority.NORMAL.value: 2,
}

_STATUS_RANK: dict[str, int] = {
    AssignmentStatus.IN_PROGRESS.value: 0,
    AssignmentStatus.PENDING.value: 1,
}

_TERMINAL_STATUSES = frozenset(
    {
        AssignmentStatus.COMPLETED.value,
        AssignmentStatus.CANCELLED.value,
    }
)

_FAR_FUTURE = datetime.max.replace(tzinfo=UTC)
_FAR_PAST = datetime.min.replace(tzinfo=UTC)


def is_assignment_overdue(
    due_at: datetime | None,
    status: str,
    *,
    now: datetime | None = None,
) -> bool:
    """True when due_at is in the past and the assignment is still open."""
    if due_at is None:
        return False
    if status in _TERMINAL_STATUSES:
        return False
    current = now or datetime.now(UTC)
    due = due_at if due_at.tzinfo is not None else due_at.replace(tzinfo=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return due < current


def assignment_sort_key(
    *,
    priority: str,
    due_at: datetime | None,
    status: str,
    assigned_at: datetime | None,
) -> tuple[int, int, datetime, int, datetime]:
    """critical → important → normal, then nearest deadline, then in_progress."""
    due = due_at if due_at is None or due_at.tzinfo is not None else due_at.replace(tzinfo=UTC)
    assigned = assigned_at
    if assigned is not None and assigned.tzinfo is None:
        assigned = assigned.replace(tzinfo=UTC)
    return (
        PRIORITY_RANK.get(priority, 9),
        0 if due is not None else 1,
        due if due is not None else _FAR_FUTURE,
        _STATUS_RANK.get(status, 2),
        assigned if assigned is not None else _FAR_PAST,
    )
