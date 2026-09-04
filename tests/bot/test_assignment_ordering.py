"""Telegram active assignment lists follow priority then deadline ordering."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.bot.api.client import OnboardApiClient
from app.bot.api.schemas import AssignmentDTO, EmployeeDTO, ProgramDTO
from app.bot.handlers.cabinet import active_assignments
from app.bot.keyboards.menu import MENU_ACTIVE
from app.db.enums import AssignmentPriority, AssignmentStatus

pytestmark = pytest.mark.telegram

TEST_ID = 9_400_000_099


def _assignment(*, priority: str, due_at, status: str = "pending") -> AssignmentDTO:
    return AssignmentDTO(
        id=uuid4(),
        company_id=uuid4(),
        employee_id=uuid4(),
        program_id=uuid4(),
        status=status,
        assigned_at=datetime.now(UTC) - timedelta(days=3),
        due_at=due_at,
        priority=priority,
    )


@pytest.mark.asyncio
async def test_get_active_assignment_prefers_critical_over_recent_normal() -> None:
    client = OnboardApiClient.__new__(OnboardApiClient)
    now = datetime.now(UTC)
    normal = _assignment(
        priority=AssignmentPriority.NORMAL.value,
        due_at=now + timedelta(days=1),
        status=AssignmentStatus.IN_PROGRESS.value,
    )
    critical = _assignment(
        priority=AssignmentPriority.CRITICAL.value,
        due_at=now + timedelta(days=10),
        status=AssignmentStatus.PENDING.value,
    )
    client.list_assignments = AsyncMock(  # type: ignore[method-assign]
        side_effect=lambda _eid, status=None: {
            "in_progress": [normal],
            "pending": [critical],
        }.get(status, [])
    )
    chosen = await client.get_active_assignment(uuid4())
    assert chosen is not None
    assert chosen.id == critical.id


@pytest.mark.asyncio
async def test_cabinet_active_lists_critical_first() -> None:
    now = datetime.now(UTC)
    normal = _assignment(
        priority=AssignmentPriority.NORMAL.value,
        due_at=now + timedelta(days=1),
    )
    important = _assignment(
        priority=AssignmentPriority.IMPORTANT.value,
        due_at=now + timedelta(days=5),
    )
    api = MagicMock()
    api.find_employee_by_telegram = AsyncMock(
        return_value=EmployeeDTO(
            id=uuid4(),
            company_id=uuid4(),
            telegram_user_id=TEST_ID,
            full_name="Ada",
            role="employee",
            status="active",
        )
    )
    api.list_assignments = AsyncMock(
        side_effect=lambda _eid, status=None: {
            "in_progress": [],
            "pending": [normal, important],
        }.get(status, [])
    )
    api.get_program = AsyncMock(
        side_effect=lambda program_id: ProgramDTO(
            id=program_id,
            company_id=uuid4(),
            title=f"P-{program_id}",
            is_active=True,
        )
    )
    api.get_progress = AsyncMock(return_value=MagicMock(percentage=0, items=[]))
    api.first_incomplete_step = MagicMock(return_value=None)

    message = MagicMock()
    message.text = MENU_ACTIVE
    message.from_user = MagicMock()
    message.from_user.id = TEST_ID
    message.chat = MagicMock()
    message.chat.id = TEST_ID
    message.answer = AsyncMock()
    state = AsyncMock()
    state.clear = AsyncMock()

    await active_assignments(message, api, state)
    text = message.answer.await_args.args[0]
    important_pos = text.find(f"P-{important.program_id}")
    normal_pos = text.find(f"P-{normal.program_id}")
    assert important_pos != -1
    assert normal_pos != -1
    assert important_pos < normal_pos
