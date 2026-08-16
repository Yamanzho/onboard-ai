from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import AssignmentStatus, CompanyAuditAction, EmployeeStatus, ProgressStatus
from app.db.models.assignment import Assignment
from app.db.models.progress import Progress
from app.db.uow import UnitOfWork
from app.services.company_audit import record_company_audit
from app.services.tenancy import ensure_same_company


class AssignmentService:
    """Application service for assigning onboarding programs to employees."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def assign_employee(
        self,
        *,
        employee_id: UUID,
        program_id: UUID,
        company_id: UUID,
        assigned_by_id: UUID | None = None,
        due_at: datetime | None = None,
        actor_employee_id: UUID | None = None,
    ) -> Assignment:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            ensure_same_company(
                resource_company_id=employee.company_id,
                actor_company_id=company_id,
                not_found_message=f"Employee {employee_id} not found",
            )
            if employee.status == EmployeeStatus.ARCHIVED.value:
                raise ValidationError("Cannot assign a program to an archived employee")

            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Onboarding program {program_id} not found",
            )
            if not program.is_active:
                raise ValidationError("Cannot assign an unpublished/archived program")
            if program.company_id != employee.company_id:
                raise ValidationError("Employee and program must belong to the same company")

            if assigned_by_id is not None:
                assigner = await uow.employees.get_by_id(assigned_by_id)
                if assigner is None:
                    raise NotFoundError(f"Employee {assigned_by_id} not found")
                ensure_same_company(
                    resource_company_id=assigner.company_id,
                    actor_company_id=company_id,
                    not_found_message=f"Employee {assigned_by_id} not found",
                )
                if assigner.company_id != employee.company_id:
                    raise ValidationError("Assigner must belong to the same company")

            steps = await uow.steps.list_by_program_id(program_id)
            if not steps:
                raise ValidationError("Cannot assign a program without steps")

            now = datetime.now(UTC)
            try:
                assignment = await uow.assignments.create(
                    Assignment(
                        company_id=employee.company_id,
                        employee_id=employee_id,
                        program_id=program_id,
                        assigned_by_id=assigned_by_id,
                        status=AssignmentStatus.PENDING.value,
                        assigned_at=now,
                        due_at=due_at,
                    ),
                )
                for step in steps:
                    await uow.progress.create(
                        Progress(
                            company_id=employee.company_id,
                            assignment_id=assignment.id,
                            step_id=step.id,
                            status=ProgressStatus.NOT_STARTED.value,
                        ),
                    )
                await record_company_audit(
                    uow,
                    company_id=employee.company_id,
                    actor_employee_id=actor_employee_id or assigned_by_id,
                    action=CompanyAuditAction.ASSIGNMENT_CREATED.value,
                    resource_type="assignment",
                    resource_id=assignment.id,
                    summary="Assigned onboarding program",
                    details={
                        "employee_id": str(employee_id),
                        "program_id": str(program_id),
                    },
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    "Employee already has an active assignment for this program"
                ) from exc
            return assignment

    async def cancel_assignment(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID | None = None,
    ) -> Assignment:
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
                raise ValidationError("Assignment is already cancelled")
            if assignment.status == AssignmentStatus.COMPLETED.value:
                raise ValidationError("Completed assignment cannot be cancelled")

            updated = await uow.assignments.update(
                assignment_id,
                status=AssignmentStatus.CANCELLED.value,
            )
            assert updated is not None
            await record_company_audit(
                uow,
                company_id=company_id,
                actor_employee_id=actor_employee_id,
                action=CompanyAuditAction.ASSIGNMENT_CHANGED.value,
                resource_type="assignment",
                resource_id=assignment_id,
                summary="Cancelled assignment",
                details={"status": AssignmentStatus.CANCELLED.value},
            )
            await uow.commit()
            return updated

    async def get_assignment(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
    ) -> Assignment:
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
            return assignment

    async def get_employee_assignments(
        self,
        employee_id: UUID,
        *,
        company_id: UUID,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[Assignment]:
        if status is not None and status not in {item.value for item in AssignmentStatus}:
            raise ValidationError(f"Invalid assignment status {status!r}")

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            ensure_same_company(
                resource_company_id=employee.company_id,
                actor_company_id=company_id,
                not_found_message=f"Employee {employee_id} not found",
            )
            return await uow.assignments.list_by_employee_id(
                employee_id,
                offset=offset,
                limit=limit,
                status=status,
            )

    async def list_assignments(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
        employee_id: UUID | None = None,
    ) -> list[Assignment]:
        if status is not None and status not in {item.value for item in AssignmentStatus}:
            raise ValidationError(f"Invalid assignment status {status!r}")
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
            if employee_id is not None:
                employee = await uow.employees.get_by_id(employee_id)
                if employee is None:
                    raise NotFoundError(f"Employee {employee_id} not found")
                ensure_same_company(
                    resource_company_id=employee.company_id,
                    actor_company_id=actor_company_id,
                    not_found_message=f"Employee {employee_id} not found",
                )
            return await uow.assignments.list_by_company_id(
                company_id,
                offset=offset,
                limit=limit,
                status=status,
                employee_id=employee_id,
            )
