from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.core.exceptions import NotFoundError, ValidationError
from app.db.models.onboarding_program import OnboardingProgram
from app.db.uow import UnitOfWork
from app.services.tenancy import ensure_same_company


class OnboardingProgramService:
    """Application service for onboarding program lifecycle."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def create_program(
        self,
        *,
        company_id: UUID,
        actor_company_id: UUID,
        title: str,
        description: str | None = None,
    ) -> OnboardingProgram:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")

            program = await uow.onboarding_programs.create(
                OnboardingProgram(
                    company_id=company_id,
                    title=title,
                    description=description,
                    is_active=False,
                ),
            )
            await uow.commit()
            return program

    async def update_program(
        self,
        program_id: UUID,
        *,
        company_id: UUID,
        **values: Any,
    ) -> OnboardingProgram:
        forbidden = {"id", "company_id", "created_at", "is_active"}
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(f"Cannot update fields via update_program: {sorted(extra)}")

        async with self._uow_factory() as uow:
            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Onboarding program {program_id} not found",
            )
            updated = await uow.onboarding_programs.update(program_id, **values)
            if updated is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            await uow.commit()
            return updated

    async def publish_program(
        self,
        program_id: UUID,
        *,
        company_id: UUID,
    ) -> OnboardingProgram:
        async with self._uow_factory() as uow:
            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Onboarding program {program_id} not found",
            )

            steps = await uow.steps.list_by_program_id(program_id)
            if not steps:
                raise ValidationError("Cannot publish a program without steps")

            updated = await uow.onboarding_programs.update(program_id, is_active=True)
            assert updated is not None
            await uow.commit()
            return updated

    async def archive_program(
        self,
        program_id: UUID,
        *,
        company_id: UUID,
    ) -> OnboardingProgram:
        async with self._uow_factory() as uow:
            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Onboarding program {program_id} not found",
            )
            updated = await uow.onboarding_programs.update(program_id, is_active=False)
            if updated is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            await uow.commit()
            return updated

    async def list_programs(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        offset: int = 0,
        limit: int = 100,
        is_active: bool | None = None,
    ) -> list[OnboardingProgram]:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            return await uow.onboarding_programs.list_by_company_id(
                company_id,
                offset=offset,
                limit=limit,
                is_active=is_active,
            )

    async def get_program(
        self,
        program_id: UUID,
        *,
        company_id: UUID,
    ) -> OnboardingProgram:
        async with self._uow_factory() as uow:
            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Onboarding program {program_id} not found",
            )
            return program
