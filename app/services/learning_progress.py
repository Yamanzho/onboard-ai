"""Block-by-block learning progression for content steps.

Quiz definitions and scoring stay in ``assessment``. Assignment completion
stays in ``ProgressService``. This module owns the content-block cursor.

``block_index`` is the index of the block currently displayed / resumed.
Example with 3 blocks: start at 0; after block 0 is consumed, index is 1;
after block 1, index is 2; acknowledging the last block completes the step.

Database ``Progress.payload`` is the source of truth. Telegram FSM is UI only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import AssignmentStatus, ProgressStatus, StepType
from app.db.models.progress import Progress
from app.db.uow import UnitOfWork
from app.services.course_snapshot import resolve_progress_step_fields
from app.services.progress import ProgressService
from app.services.step_content import normalize_step_content, payload_block_index
from app.services.tenancy import ensure_same_company

_DONE_STATUSES = frozenset(
    {
        ProgressStatus.COMPLETED.value,
        ProgressStatus.SKIPPED.value,
    }
)
_CONTENT_TYPES = frozenset({StepType.CONTENT.value})


def current_block_index(payload: dict[str, Any] | None) -> int:
    """Resume cursor. Missing/invalid payload starts at block 0."""
    index = payload_block_index(payload)
    return 0 if index is None else index


def content_block_count(content: dict[str, Any] | None) -> int:
    return len(normalize_step_content(content))


def is_final_block(block_index: int, block_count: int) -> bool:
    if block_count <= 0:
        return True
    return block_index >= block_count - 1


def resolve_resume_item(items: Sequence[Any]) -> Any | None:
    """Prefer the first in-progress row, else the first incomplete row."""
    in_progress = None
    first_open = None
    for item in items:
        status = getattr(item, "status", None)
        if status == ProgressStatus.IN_PROGRESS.value and in_progress is None:
            in_progress = item
        if status not in _DONE_STATUSES and first_open is None:
            first_open = item
    return in_progress if in_progress is not None else first_open


def merge_learning_payload(
    existing: dict[str, Any] | None,
    **fields: Any,
) -> dict[str, Any]:
    payload = dict(existing) if isinstance(existing, dict) else {}
    payload.update(fields)
    return payload


class LearningProgressService:
    """Start, resume, and advance content-block progress through the API."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        progress_service: ProgressService | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._progress = progress_service or ProgressService(uow_factory=self._uow_factory)

    async def start_or_resume(
        self,
        progress_id: UUID,
        *,
        company_id: UUID,
    ) -> Progress:
        async with self._uow_factory() as uow:
            progress, _assignment, _step_type, _content, _count = (
                await self._load_mutable(uow, progress_id, company_id)
            )
            if progress.status == ProgressStatus.COMPLETED.value:
                raise ConflictError("Step is already completed")
            now = datetime.now(UTC)
            just_started = await self._ensure_started(
                uow, progress=progress, assignment_id=progress.assignment_id, now=now
            )
            if just_started:
                await uow.commit()
                refreshed = await uow.progress.get_by_id(progress.id)
                assert refreshed is not None
                return refreshed
            await uow.commit()
            return progress

    async def advance_block(
        self,
        progress_id: UUID,
        *,
        company_id: UUID,
        expected_block_index: int,
    ) -> Progress:
        if expected_block_index < 0:
            raise ValidationError("expected_block_index must be >= 0")
        async with self._uow_factory() as uow:
            progress, _assignment, step_type, _content, block_count = (
                await self._load_mutable(uow, progress_id, company_id)
            )
            self._require_content_step(step_type)
            if progress.status == ProgressStatus.COMPLETED.value:
                raise ConflictError("Step is already completed")
            now = datetime.now(UTC)
            just_started = await self._ensure_started(
                uow, progress=progress, assignment_id=progress.assignment_id, now=now
            )
            progress = await uow.progress.get_by_id(progress.id)
            assert progress is not None
            if just_started:
                await uow.commit()
                return progress
            current = current_block_index(progress.payload)
            if expected_block_index != current:
                await uow.commit()
                return progress
            if is_final_block(current, block_count):
                await uow.commit()
                return progress
            payload = merge_learning_payload(
                progress.payload,
                block_index=current + 1,
                content_started=True,
            )
            updated = await uow.progress.update(progress.id, payload=payload)
            assert updated is not None
            await uow.commit()
            return updated

    async def complete_content_block(
        self,
        progress_id: UUID,
        *,
        company_id: UUID,
        expected_block_index: int,
        telegram_outbound_employee_id: UUID | None = None,
    ) -> Progress:
        if expected_block_index < 0:
            raise ValidationError("expected_block_index must be >= 0")
        async with self._uow_factory() as uow:
            progress, _assignment, step_type, _content, block_count = (
                await self._load_mutable(uow, progress_id, company_id)
            )
            self._require_content_step(step_type)
            if progress.status == ProgressStatus.COMPLETED.value:
                raise ConflictError("Step is already completed")
            now = datetime.now(UTC)
            just_started = await self._ensure_started(
                uow, progress=progress, assignment_id=progress.assignment_id, now=now
            )
            progress = await uow.progress.get_by_id(progress.id)
            assert progress is not None
            current = current_block_index(progress.payload)
            if (
                just_started
                and expected_block_index == 0
                and is_final_block(0, block_count)
            ):
                pass
            elif expected_block_index != current or not is_final_block(
                current, block_count
            ):
                await uow.commit()
                return progress
            payload = merge_learning_payload(
                progress.payload,
                block_index=current,
                content_started=True,
            )
            assignment_id = progress.assignment_id
            step_id = progress.step_id
        return await self._progress.complete_step(
            assignment_id=assignment_id,
            step_id=step_id,
            company_id=company_id,
            payload=payload,
            telegram_outbound_employee_id=telegram_outbound_employee_id,
        )

    async def _load_mutable(
        self,
        uow: UnitOfWork,
        progress_id: UUID,
        company_id: UUID,
    ) -> tuple[Progress, Any, str, dict[str, Any], int]:
        await uow.enter_tenant(company_id)
        progress = await uow.progress.get_by_id(progress_id)
        if progress is None:
            raise NotFoundError(f"Progress {progress_id} not found")
        assignment = await uow.assignments.get_by_id(progress.assignment_id)
        if assignment is None:
            raise NotFoundError(f"Progress {progress_id} not found")
        ensure_same_company(
            resource_company_id=assignment.company_id,
            actor_company_id=company_id,
            not_found_message=f"Progress {progress_id} not found",
        )
        if progress.status == ProgressStatus.COMPLETED.value:
            raise ConflictError("Step is already completed")
        if assignment.status == AssignmentStatus.CANCELLED.value:
            raise ValidationError("Cannot update progress on a cancelled assignment")
        if assignment.status == AssignmentStatus.COMPLETED.value:
            raise ValidationError("Assignment is already completed")
        live_step = await uow.steps.get_by_id(progress.step_id)
        resolved = resolve_progress_step_fields(
            progress.step_id,
            live_step=live_step,
            snapshot=assignment.structure_snapshot,
        )
        if resolved is None:
            raise ValidationError("Step is no longer available")
        content = dict(resolved["content"]) if isinstance(resolved["content"], dict) else {}
        step_type = str(resolved["step_type"])
        return progress, assignment, step_type, content, content_block_count(content)

    async def _ensure_started(
        self,
        uow: UnitOfWork,
        *,
        progress: Progress,
        assignment_id: UUID,
        now: datetime,
    ) -> bool:
        if progress.status != ProgressStatus.NOT_STARTED.value:
            return False
        payload = merge_learning_payload(
            progress.payload,
            block_index=0,
            content_started=True,
        )
        values: dict[str, Any] = {
            "status": ProgressStatus.IN_PROGRESS.value,
            "payload": payload,
        }
        if progress.started_at is None:
            values["started_at"] = now
        updated = await uow.progress.update(progress.id, **values)
        assert updated is not None
        assignment = await uow.assignments.get_by_id(assignment_id)
        if assignment is not None and assignment.status == AssignmentStatus.PENDING.value:
            await uow.assignments.update(
                assignment_id,
                status=AssignmentStatus.IN_PROGRESS.value,
                started_at=now,
            )
        return True

    @staticmethod
    def _require_content_step(step_type: str) -> None:
        if step_type not in _CONTENT_TYPES:
            raise ValidationError("Block navigation applies only to content steps")
