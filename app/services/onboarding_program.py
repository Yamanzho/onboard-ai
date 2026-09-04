from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.core.exceptions import NotFoundError, ValidationError
from app.db.enums import AssignmentStatus, CompanyAuditAction, EmployeeRole
from app.db.models.onboarding_program import OnboardingProgram
from app.db.uow import UnitOfWork
from app.services.company_audit import record_company_audit
from app.services.subscription_guard import ensure_program_limit
from app.services.tenancy import ensure_same_company

# HR/Admin manage drafts/archives; employees only see published or assigned programs.
_PROGRAM_MANAGEMENT_ROLES = frozenset(
    {
        EmployeeRole.ADMIN.value,
        EmployeeRole.HR.value,
    }
)
# Same grant set as program-scoped KB: cancelled does not grant visibility.
_ASSIGNMENT_STATUSES_GRANTING_PROGRAM_READ = frozenset(
    {
        AssignmentStatus.PENDING.value,
        AssignmentStatus.IN_PROGRESS.value,
        AssignmentStatus.COMPLETED.value,
    }
)


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
        actor_employee_id: UUID | None = None,
    ) -> OnboardingProgram:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            await ensure_program_limit(uow, company_id)

            program = await uow.onboarding_programs.create(
                OnboardingProgram(
                    company_id=company_id,
                    title=title,
                    description=description,
                    is_active=False,
                ),
            )
            await record_company_audit(
                uow,
                company_id=company_id,
                actor_employee_id=actor_employee_id,
                action=CompanyAuditAction.PROGRAM_CREATED.value,
                resource_type="program",
                resource_id=program.id,
                summary=f"Created program {title!r}",
            )
            await uow.commit()
            return self._with_lock_state(program, locked=False)

    async def update_program(
        self,
        program_id: UUID,
        *,
        company_id: UUID,
        **values: Any,
    ) -> OnboardingProgram:
        forbidden = {
            "id",
            "company_id",
            "created_at",
            "is_active",
            "revision",
            "structure_locked",
            "can_edit_structure",
        }
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(f"Cannot update fields via update_program: {sorted(extra)}")

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
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
            locked = await uow.assignments.has_active_for_program(program_id)
            await uow.commit()
            return self._with_lock_state(updated, locked=locked)

    async def publish_program(
        self,
        program_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID | None = None,
    ) -> OnboardingProgram:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
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
            await record_company_audit(
                uow,
                company_id=company_id,
                actor_employee_id=actor_employee_id,
                action=CompanyAuditAction.PROGRAM_PUBLISHED.value,
                resource_type="program",
                resource_id=program_id,
                summary=f"Published program {program.title!r}",
            )
            locked = await uow.assignments.has_active_for_program(program_id)
            await uow.commit()
            return self._with_lock_state(updated, locked=locked)

    async def archive_program(
        self,
        program_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID | None = None,
    ) -> OnboardingProgram:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
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
            await record_company_audit(
                uow,
                company_id=company_id,
                actor_employee_id=actor_employee_id,
                action=CompanyAuditAction.PROGRAM_ARCHIVED.value,
                resource_type="program",
                resource_id=program_id,
                summary=f"Archived program {program.title!r}",
            )
            locked = await uow.assignments.has_active_for_program(program_id)
            await uow.commit()
            return self._with_lock_state(updated, locked=locked)

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
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            programs = await uow.onboarding_programs.list_by_company_id(
                company_id,
                offset=offset,
                limit=limit,
                is_active=is_active,
            )
            locked_ids = await uow.assignments.list_program_ids_with_active_assignments(
                [program.id for program in programs],
            )
            return [
                self._with_lock_state(program, locked=program.id in locked_ids)
                for program in programs
            ]

    async def get_program(
        self,
        program_id: UUID,
        *,
        company_id: UUID,
        actor_role: str,
        actor_employee_id: UUID | None = None,
    ) -> OnboardingProgram:
        """Load a program for the actor within ``company_id``.

        HR/Admin may read any same-tenant program (including draft/archived).
        Employees may read **published** (``is_active``) programs in-tenant, or
        an unpublished program only when they have a non-cancelled assignment to
        it (e.g. bot UX after archive). Unauthorized access returns NotFoundError
        to avoid existence enumeration.
        """
        not_found = f"Onboarding program {program_id} not found"
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(not_found)
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=not_found,
            )

            if actor_role in _PROGRAM_MANAGEMENT_ROLES:
                locked = await uow.assignments.has_active_for_program(program_id)
                return self._with_lock_state(program, locked=locked)

            if program.is_active:
                locked = await uow.assignments.has_active_for_program(program_id)
                return self._with_lock_state(program, locked=locked)

            # Unpublished/draft/archived: only the assigned employee may read.
            if actor_employee_id is None:
                raise NotFoundError(not_found)
            if await self._employee_has_program_assignment(
                uow,
                program_id=program_id,
                employee_id=actor_employee_id,
            ):
                locked = await uow.assignments.has_active_for_program(program_id)
                return self._with_lock_state(program, locked=locked)
            raise NotFoundError(not_found)

    @staticmethod
    def _with_lock_state(program: OnboardingProgram, *, locked: bool) -> OnboardingProgram:
        program.structure_locked = locked
        program.can_edit_structure = not locked
        return program

    @staticmethod
    async def _employee_has_program_assignment(
        uow: UnitOfWork,
        *,
        program_id: UUID,
        employee_id: UUID,
    ) -> bool:
        assignments = await uow.assignments.list_by_employee_id(
            employee_id,
            offset=0,
            limit=1000,
        )
        return any(
            assignment.program_id == program_id
            and assignment.status in _ASSIGNMENT_STATUSES_GRANTING_PROGRAM_READ
            for assignment in assignments
        )
