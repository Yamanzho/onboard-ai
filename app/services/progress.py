from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import AssignmentStatus, ProgressStatus
from app.db.models.progress import Progress
from app.db.uow import UnitOfWork
from app.services.tenancy import ensure_same_company

_DONE_STATUSES = {
    ProgressStatus.COMPLETED.value,
    ProgressStatus.SKIPPED.value,
}


class ProgressService:
    """Application service for assignment step progress."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def complete_step(
        self,
        *,
        assignment_id: UUID,
        step_id: UUID,
        company_id: UUID,
        payload: dict[str, Any] | None = None,
    ) -> Progress:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            assignment = await uow.assignments.get_by_id(assignment_id)
            if assignment is None:
                raise NotFoundError(f"Assignment {assignment_id} not found")
            ensure_same_company(
                resource_company_id=assignment.company_id,
                actor_company_id=company_id,
                not_found_message=f"Assignment {assignment_id} not found",
            )
            if assignment.status == AssignmentStatus.CANCELLED.value:
                raise ValidationError("Cannot complete steps on a cancelled assignment")
            if assignment.status == AssignmentStatus.COMPLETED.value:
                raise ValidationError("Assignment is already completed")

            step = await uow.steps.get_by_id(step_id)
            if step is None:
                raise NotFoundError(f"Step {step_id} not found")
            if step.program_id != assignment.program_id:
                raise ValidationError("Step does not belong to the assigned program")

            progress = await uow.progress.get_by_assignment_and_step(assignment_id, step_id)
            if progress is None:
                raise NotFoundError(
                    f"Progress for assignment {assignment_id} and step {step_id} not found"
                )
            if progress.status == ProgressStatus.COMPLETED.value:
                raise ConflictError("Step is already completed")

            now = datetime.now(UTC)
            values: dict[str, Any] = {
                "status": ProgressStatus.COMPLETED.value,
                "completed_at": now,
            }
            if payload is not None:
                values["payload"] = payload
            if progress.started_at is None:
                values["started_at"] = now

            updated = await uow.progress.update(progress.id, **values)
            assert updated is not None

            if assignment.status == AssignmentStatus.PENDING.value:
                await uow.assignments.update(
                    assignment_id,
                    status=AssignmentStatus.IN_PROGRESS.value,
                    started_at=now,
                )

            records = await uow.progress.list_by_assignment_id(assignment_id)
            if self._all_required_done(
                records,
                await uow.steps.list_by_program_id(assignment.program_id),
            ):
                await uow.assignments.update(
                    assignment_id,
                    status=AssignmentStatus.COMPLETED.value,
                    completed_at=now,
                )

            await uow.commit()
            return updated

    async def complete_by_progress_id(
        self,
        progress_id: UUID,
        *,
        company_id: UUID,
        payload: dict[str, Any] | None = None,
    ) -> Progress:
        async with self._uow_factory() as uow:
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
            assignment_id = progress.assignment_id
            step_id = progress.step_id

        return await self.complete_step(
            assignment_id=assignment_id,
            step_id=step_id,
            company_id=company_id,
            payload=payload,
        )

    async def get_progress_by_id(
        self,
        progress_id: UUID,
        *,
        company_id: UUID,
    ) -> Progress:
        async with self._uow_factory() as uow:
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
            return progress

    async def get_progress(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
    ) -> list[Progress]:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            assignment = await uow.assignments.get_by_id(assignment_id)
            if assignment is None:
                raise NotFoundError(f"Assignment {assignment_id} not found")
            ensure_same_company(
                resource_company_id=assignment.company_id,
                actor_company_id=company_id,
                not_found_message=f"Assignment {assignment_id} not found",
            )
            return await uow.progress.list_by_assignment_id(assignment_id)

    async def get_steps_for_progress_items(
        self,
        items: list[Progress],
        *,
        company_id: UUID,
    ) -> dict[UUID, Any]:
        """Load step rows for progress items (title/description/content for bot)."""
        step_ids = {item.step_id for item in items}
        if not step_ids:
            return {}
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            steps: dict[UUID, Any] = {}
            for step_id in step_ids:
                step = await uow.steps.get_by_id(step_id)
                if step is None:
                    continue
                ensure_same_company(
                    resource_company_id=step.company_id,
                    actor_company_id=company_id,
                    not_found_message=f"Step {step_id} not found",
                )
                steps[step.id] = step
            return steps

    async def calculate_progress_percentage(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
    ) -> float:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            assignment = await uow.assignments.get_by_id(assignment_id)
            if assignment is None:
                raise NotFoundError(f"Assignment {assignment_id} not found")
            ensure_same_company(
                resource_company_id=assignment.company_id,
                actor_company_id=company_id,
                not_found_message=f"Assignment {assignment_id} not found",
            )

            records = await uow.progress.list_by_assignment_id(assignment_id)
            if not records:
                return 0.0

            done = sum(1 for record in records if record.status in _DONE_STATUSES)
            return round((done / len(records)) * 100.0, 2)

    @staticmethod
    def _all_required_done(records: list[Progress], steps: list) -> bool:
        step_by_id = {step.id: step for step in steps}
        for record in records:
            step = step_by_id.get(record.step_id)
            if step is None:
                continue
            if step.is_required and record.status not in _DONE_STATUSES:
                return False
        required_steps = [step for step in steps if step.is_required]
        if not required_steps:
            return all(record.status in _DONE_STATUSES for record in records)
        return True
