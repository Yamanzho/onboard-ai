from collections.abc import Callable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import StepType
from app.db.models.step import Step
from app.db.uow import UnitOfWork
from app.services.tenancy import ensure_same_company

_ALLOWED_STEP_TYPES = {item.value for item in StepType}


class StepService:
    """Application service for onboarding program steps."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def list_steps(
        self,
        program_id: UUID,
        *,
        company_id: UUID,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[Step]:
        """List steps for a program within the caller's tenant, ordered by position."""
        async with self._uow_factory() as uow:
            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Onboarding program {program_id} not found",
            )
            return await uow.steps.list_by_program_id(
                program_id,
                offset=offset,
                limit=limit,
            )

    async def create_step(
        self,
        *,
        program_id: UUID,
        company_id: UUID,
        title: str,
        description: str | None = None,
        step_type: str = StepType.CONTENT.value,
        position: int | None = None,
        content: dict[str, Any] | None = None,
        is_required: bool = True,
        estimated_minutes: int | None = None,
    ) -> Step:
        if step_type not in _ALLOWED_STEP_TYPES:
            raise ValidationError(
                f"Invalid step_type {step_type!r}; expected one of {sorted(_ALLOWED_STEP_TYPES)}"
            )
        if estimated_minutes is not None and estimated_minutes < 0:
            raise ValidationError("estimated_minutes must be >= 0")

        async with self._uow_factory() as uow:
            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Onboarding program {program_id} not found",
            )

            if position is None:
                max_position = await uow.steps.get_max_position(program_id)
                position = 0 if max_position is None else max_position + 1
            elif position < 0:
                raise ValidationError("position must be >= 0")

            try:
                step = await uow.steps.create(
                    Step(
                        program_id=program_id,
                        title=title,
                        description=description,
                        step_type=step_type,
                        position=position,
                        content=content if content is not None else {},
                        is_required=is_required,
                        estimated_minutes=estimated_minutes,
                    ),
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Step position {position} already exists in program {program_id}"
                ) from exc
            return step

    async def update_step(
        self,
        step_id: UUID,
        *,
        company_id: UUID,
        **values: Any,
    ) -> Step:
        forbidden = {"id", "program_id", "created_at", "position"}
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(
                f"Cannot update fields via update_step: {sorted(extra)}; "
                "use reorder_steps() to change position"
            )
        if "step_type" in values and values["step_type"] not in _ALLOWED_STEP_TYPES:
            raise ValidationError(
                f"Invalid step_type {values['step_type']!r}; "
                f"expected one of {sorted(_ALLOWED_STEP_TYPES)}"
            )
        if "estimated_minutes" in values:
            minutes = values["estimated_minutes"]
            if minutes is not None and minutes < 0:
                raise ValidationError("estimated_minutes must be >= 0")

        async with self._uow_factory() as uow:
            step = await uow.steps.get_by_id(step_id)
            if step is None:
                raise NotFoundError(f"Step {step_id} not found")
            program = await uow.onboarding_programs.get_by_id(step.program_id)
            if program is None:
                raise NotFoundError(f"Step {step_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Step {step_id} not found",
            )
            updated = await uow.steps.update(step_id, **values)
            if updated is None:
                raise NotFoundError(f"Step {step_id} not found")
            await uow.commit()
            return updated

    async def reorder_steps(
        self,
        program_id: UUID,
        step_ids: Sequence[UUID],
        *,
        company_id: UUID,
    ) -> list[Step]:
        if not step_ids:
            raise ValidationError("step_ids must not be empty")
        if len(step_ids) != len(set(step_ids)):
            raise ValidationError("step_ids must be unique")

        async with self._uow_factory() as uow:
            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Onboarding program {program_id} not found",
            )

            existing = await uow.steps.list_by_program_id(program_id)
            existing_ids = {step.id for step in existing}
            requested_ids = set(step_ids)

            if requested_ids != existing_ids:
                raise ValidationError(
                    "step_ids must contain exactly all steps of the program"
                )

            # Two-phase update avoids unique (program_id, position) conflicts.
            # Temporary positions must stay >= 0 (ck_steps_position_non_negative).
            max_position = max((step.position for step in existing), default=-1)
            temp_base = max_position + 1 + len(existing)
            for index, step_id in enumerate(step_ids):
                await uow.steps.update(step_id, position=temp_base + index)

            ordered: list[Step] = []
            for index, step_id in enumerate(step_ids):
                updated = await uow.steps.update(step_id, position=index)
                assert updated is not None
                ordered.append(updated)

            await uow.commit()
            return ordered

    async def delete_step(
        self,
        step_id: UUID,
        *,
        company_id: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            step = await uow.steps.get_by_id(step_id)
            if step is None:
                raise NotFoundError(f"Step {step_id} not found")

            program = await uow.onboarding_programs.get_by_id(step.program_id)
            if program is None:
                raise NotFoundError(f"Step {step_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Step {step_id} not found",
            )

            program_id = step.program_id
            try:
                deleted = await uow.steps.delete(step_id)
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Step {step_id} cannot be deleted while progress records exist"
                ) from exc

            if not deleted:
                raise NotFoundError(f"Step {step_id} not found")

            remaining = await uow.steps.list_by_program_id(program_id)
            # Two-phase renumber; keep temporary positions >= 0 for CHECK constraint.
            max_position = max((step.position for step in remaining), default=-1)
            temp_base = max_position + 1 + len(remaining)
            for index, remaining_step in enumerate(remaining):
                await uow.steps.update(
                    remaining_step.id,
                    position=temp_base + index,
                )
            for index, remaining_step in enumerate(remaining):
                await uow.steps.update(remaining_step.id, position=index)

            await uow.commit()
