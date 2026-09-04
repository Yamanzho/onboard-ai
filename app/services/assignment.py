from collections.abc import Callable, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import (
    AssignmentPriority,
    AssignmentStatus,
    AssignmentType,
    CompanyAuditAction,
    EmployeeStatus,
    KnowledgeArticleStatus,
    ProgressStatus,
)
from app.db.models.assignment import Assignment
from app.db.models.assignment_acknowledgement_item import AssignmentAcknowledgementItem
from app.db.models.employee import Employee
from app.db.models.knowledge_article import KnowledgeArticle
from app.db.models.knowledge_article_version import KnowledgeArticleVersion
from app.db.models.progress import Progress
from app.db.uow import UnitOfWork
from app.schemas.assignment import AcknowledgementDocumentInput
from app.services.acknowledgement import (
    acknowledgement_summary,
)
from app.services.company_audit import record_company_audit
from app.services.course_snapshot import build_structure_snapshot
from app.services.reminder import ReminderService
from app.services.tenancy import ensure_same_company

_OPEN_STATUSES = {
    AssignmentStatus.PENDING.value,
    AssignmentStatus.IN_PROGRESS.value,
}

_VALID_PRIORITIES = {item.value for item in AssignmentPriority}


class AssignmentService:
    """Application service for assigning onboarding programs to employees."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        reminder_service: ReminderService | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._reminders = reminder_service or ReminderService(
            uow_factory=self._uow_factory
        )

    async def assign_employee(
        self,
        *,
        employee_id: UUID,
        program_id: UUID,
        company_id: UUID,
        assigned_by_id: UUID | None = None,
        due_at: datetime | None = None,
        priority: str = AssignmentPriority.NORMAL.value,
        actor_employee_id: UUID | None = None,
    ) -> Assignment:
        created = await self.create_many(
            company_id=company_id,
            program_id=program_id,
            employee_ids=[employee_id],
            department_ids=[],
            assigned_by_id=assigned_by_id,
            due_at=due_at,
            priority=priority,
            deadline_overrides={},
            actor_employee_id=actor_employee_id,
            stamp_batch=False,
        )
        return created[0]

    async def create_many(
        self,
        *,
        company_id: UUID,
        employee_ids: Sequence[UUID],
        department_ids: Sequence[UUID],
        program_id: UUID | None = None,
        assignment_type: str = AssignmentType.PROGRAM.value,
        documents: Sequence[AcknowledgementDocumentInput] | None = None,
        assigned_by_id: UUID | None = None,
        due_at: datetime | None = None,
        priority: str = AssignmentPriority.NORMAL.value,
        deadline_overrides: dict[UUID, datetime | None] | None = None,
        actor_employee_id: UUID | None = None,
        stamp_batch: bool = True,
    ) -> list[Assignment]:
        """Resolve recipients, validate, and create one Assignment per employee.

        Program creates remain atomic against the active program unique index.
        Acknowledgement creates always start a new run.
        """
        if assignment_type == AssignmentType.ACKNOWLEDGEMENT.value:
            return await self._create_acknowledgement_many(
                company_id=company_id,
                employee_ids=employee_ids,
                department_ids=department_ids,
                documents=list(documents or []),
                assigned_by_id=assigned_by_id,
                due_at=due_at,
                priority=priority,
                deadline_overrides=deadline_overrides,
                actor_employee_id=actor_employee_id,
                stamp_batch=stamp_batch,
            )
        if program_id is None:
            raise ValidationError("program_id is required for program assignments")
        overrides = deadline_overrides or {}
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            recipients = await self.resolve_assignment_recipients(
                uow,
                company_id=company_id,
                employee_ids=list(employee_ids),
                department_ids=list(department_ids),
            )
            await self.validate_bulk_assignment(
                uow,
                company_id=company_id,
                program_id=program_id,
                recipients=recipients,
                assigned_by_id=assigned_by_id,
                priority=priority,
                deadline_overrides=overrides,
            )
            steps = await uow.steps.list_by_program_id(program_id)
            now = datetime.now(UTC)
            source_batch_id = uuid4() if stamp_batch else None
            program = await uow.onboarding_programs.get_by_id(program_id)
            program_revision = program.revision if program is not None else 1
            structure_snapshot = build_structure_snapshot(program_revision, steps)
            company = await uow.companies.get_by_id(company_id)
            assert company is not None
            program_title = program.title if program is not None else "курс"

            created: list[Assignment] = []
            try:
                for employee in recipients:
                    effective_due = (
                        overrides[employee.id]
                        if employee.id in overrides
                        else due_at
                    )
                    assignment = await uow.assignments.create(
                        Assignment(
                            company_id=employee.company_id,
                            employee_id=employee.id,
                            assignment_type=AssignmentType.PROGRAM.value,
                            program_id=program_id,
                            assigned_by_id=assigned_by_id,
                            status=AssignmentStatus.PENDING.value,
                            priority=priority,
                            source_batch_id=source_batch_id,
                            program_revision=program_revision,
                            structure_snapshot=deepcopy(structure_snapshot),
                            assigned_at=now,
                            due_at=effective_due,
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
                            "employee_id": str(employee.id),
                            "program_id": str(program_id),
                            "assignment_type": AssignmentType.PROGRAM.value,
                            "priority": priority,
                            "program_revision": program_revision,
                            "source_batch_id": (
                                str(source_batch_id) if source_batch_id else None
                            ),
                        },
                    )
                    await self._reminders.enqueue_initial_in_uow(
                        uow,
                        assignment=assignment,
                        employee=employee,
                        company=company,
                        program_title=program_title,
                        now=now,
                    )
                    created.append(assignment)
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    "Employee already has an active assignment for this program"
                ) from exc
            return created

    async def _create_acknowledgement_many(
        self,
        *,
        company_id: UUID,
        employee_ids: Sequence[UUID],
        department_ids: Sequence[UUID],
        documents: list[AcknowledgementDocumentInput],
        assigned_by_id: UUID | None,
        due_at: datetime | None,
        priority: str,
        deadline_overrides: dict[UUID, datetime | None] | None,
        actor_employee_id: UUID | None,
        stamp_batch: bool,
    ) -> list[Assignment]:
        overrides = deadline_overrides or {}
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            recipients = await self.resolve_assignment_recipients(
                uow,
                company_id=company_id,
                employee_ids=list(employee_ids),
                department_ids=list(department_ids),
            )
            await self._validate_shared_assignment_inputs(
                uow,
                company_id=company_id,
                recipients=recipients,
                assigned_by_id=assigned_by_id,
                priority=priority,
                deadline_overrides=overrides,
            )
            resolved = await self._resolve_acknowledgement_documents(
                uow,
                company_id=company_id,
                documents=documents,
            )
            now = datetime.now(UTC)
            source_batch_id = uuid4() if stamp_batch else None
            company = await uow.companies.get_by_id(company_id)
            assert company is not None
            display_title = resolved[0][1].title
            created: list[Assignment] = []
            for employee in recipients:
                effective_due = (
                    overrides[employee.id] if employee.id in overrides else due_at
                )
                assignment = await uow.assignments.create(
                    Assignment(
                        company_id=employee.company_id,
                        employee_id=employee.id,
                        assignment_type=AssignmentType.ACKNOWLEDGEMENT.value,
                        program_id=None,
                        assigned_by_id=assigned_by_id,
                        status=AssignmentStatus.PENDING.value,
                        priority=priority,
                        source_batch_id=source_batch_id,
                        program_revision=1,
                        structure_snapshot=None,
                        assigned_at=now,
                        due_at=effective_due,
                    ),
                )
                for spec, version in resolved:
                    await uow.assignment_acknowledgement_items.create(
                        AssignmentAcknowledgementItem(
                            company_id=employee.company_id,
                            assignment_id=assignment.id,
                            assignment_type=AssignmentType.ACKNOWLEDGEMENT.value,
                            article_id=spec.article_id,
                            article_version_id=version.id,
                            position=spec.position,
                            is_required=spec.is_required,
                        ),
                    )
                if not any(spec.is_required for spec, _ in resolved):
                    completed = await uow.assignments.update(
                        assignment.id,
                        status=AssignmentStatus.COMPLETED.value,
                        completed_at=now,
                    )
                    assert completed is not None
                    assignment = completed
                await record_company_audit(
                    uow,
                    company_id=employee.company_id,
                    actor_employee_id=actor_employee_id or assigned_by_id,
                    action=CompanyAuditAction.ASSIGNMENT_CREATED.value,
                    resource_type="assignment",
                    resource_id=assignment.id,
                    summary="Assigned documents for acknowledgement",
                    details={
                        "employee_id": str(employee.id),
                        "assignment_type": AssignmentType.ACKNOWLEDGEMENT.value,
                        "article_ids": [str(spec.article_id) for spec, _ in resolved],
                        "article_version_ids": [str(version.id) for _, version in resolved],
                        "priority": priority,
                        "source_batch_id": (
                            str(source_batch_id) if source_batch_id else None
                        ),
                    },
                )
                if assignment.status in _OPEN_STATUSES:
                    await self._reminders.enqueue_initial_in_uow(
                        uow,
                        assignment=assignment,
                        employee=employee,
                        company=company,
                        program_title=display_title,
                        now=now,
                    )
                created.append(assignment)
            await uow.commit()
            return created

    async def resolve_assignment_recipients(
        self,
        uow: UnitOfWork,
        *,
        company_id: UUID,
        employee_ids: list[UUID],
        department_ids: list[UUID],
    ) -> list[Employee]:
        """Snapshot-resolve eligible employees from departments and explicit IDs."""
        unique_dept_ids = list(dict.fromkeys(department_ids))
        unique_employee_ids = list(dict.fromkeys(employee_ids))

        if unique_dept_ids:
            found_departments = await uow.departments.list_by_ids(unique_dept_ids)
            found_by_id = {dept.id: dept for dept in found_departments}
            for dept_id in unique_dept_ids:
                department = found_by_id.get(dept_id)
                if department is None:
                    raise NotFoundError(f"Department {dept_id} not found")
                ensure_same_company(
                    resource_company_id=department.company_id,
                    actor_company_id=company_id,
                    not_found_message=f"Department {dept_id} not found",
                )
                if not department.is_active:
                    raise ValidationError("Cannot assign to an inactive department")

        department_members = await uow.employees.list_non_archived_by_department_ids(
            unique_dept_ids,
        )
        by_id: dict[UUID, Employee] = {}
        for employee in department_members:
            ensure_same_company(
                resource_company_id=employee.company_id,
                actor_company_id=company_id,
                not_found_message=f"Employee {employee.id} not found",
            )
            by_id[employee.id] = employee

        if unique_employee_ids:
            found_employees = await uow.employees.list_by_ids(unique_employee_ids)
            found_emp_by_id = {emp.id: emp for emp in found_employees}
            for emp_id in unique_employee_ids:
                employee = found_emp_by_id.get(emp_id)
                if employee is None:
                    raise NotFoundError(f"Employee {emp_id} not found")
                ensure_same_company(
                    resource_company_id=employee.company_id,
                    actor_company_id=company_id,
                    not_found_message=f"Employee {emp_id} not found",
                )
                if employee.status == EmployeeStatus.ARCHIVED.value:
                    raise ValidationError("Cannot assign a program to an archived employee")
                by_id.setdefault(emp_id, employee)

        if not by_id:
            raise ValidationError("No eligible recipients for this assignment")
        return list(by_id.values())

    async def validate_bulk_assignment(
        self,
        uow: UnitOfWork,
        *,
        company_id: UUID,
        program_id: UUID,
        recipients: list[Employee],
        assigned_by_id: UUID | None,
        priority: str,
        deadline_overrides: dict[UUID, datetime | None],
    ) -> None:
        await self._validate_shared_assignment_inputs(
            uow,
            company_id=company_id,
            recipients=recipients,
            assigned_by_id=assigned_by_id,
            priority=priority,
            deadline_overrides=deadline_overrides,
        )

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

        for employee in recipients:
            if program.company_id != employee.company_id:
                raise ValidationError("Employee and program must belong to the same company")

        steps = await uow.steps.list_by_program_id(program_id)
        if not steps:
            raise ValidationError("Cannot assign a program without steps")

        existing = await uow.assignments.list_active_by_program_and_employees(
            program_id,
            [employee.id for employee in recipients],
        )
        if existing:
            conflicts = [
                {
                    "employee_id": str(row.employee_id),
                    "assignment_id": str(row.id),
                    "reason": "active_assignment",
                }
                for row in existing
            ]
            raise ConflictError(
                "Employee already has an active assignment for this program",
                conflicts=conflicts,
            )

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

            discarded = await uow.progress.delete_by_assignment_id(assignment_id)
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
                details={
                    "status": AssignmentStatus.CANCELLED.value,
                    "progress_discarded": True,
                    "progress_rows_removed": discarded,
                },
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

    async def acknowledgement_summaries(
        self,
        assignments: Sequence[Assignment],
        *,
        company_id: UUID,
    ) -> dict[UUID, object]:
        ack_ids = [
            row.id
            for row in assignments
            if row.assignment_type == AssignmentType.ACKNOWLEDGEMENT.value
        ]
        if not ack_ids:
            return {}
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            items = await uow.assignment_acknowledgement_items.list_by_assignment_ids(
                ack_ids
            )
            await uow.commit()
        grouped: dict[UUID, list[AssignmentAcknowledgementItem]] = {
            item_id: [] for item_id in ack_ids
        }
        for item in items:
            grouped.setdefault(item.assignment_id, []).append(item)
        return {
            assignment_id: acknowledgement_summary(rows)
            for assignment_id, rows in grouped.items()
        }

    async def list_acknowledgement_items(
        self,
        assignment_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID | None = None,
        mark_opened: bool = False,
    ) -> tuple[Assignment, list[AssignmentAcknowledgementItem]]:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            assignment = await self._require_acknowledgement_assignment(
                uow, assignment_id, company_id
            )
            if mark_opened and actor_employee_id == assignment.employee_id:
                await self._mark_in_progress(uow, assignment)
            items = await uow.assignment_acknowledgement_items.list_by_assignment_id(
                assignment_id
            )
            await uow.commit()
            return assignment, items

    async def get_acknowledgement_document(
        self,
        assignment_id: UUID,
        item_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID | None = None,
        mark_opened: bool = False,
    ) -> tuple[Assignment, AssignmentAcknowledgementItem, KnowledgeArticleVersion]:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            assignment = await self._require_acknowledgement_assignment(
                uow, assignment_id, company_id
            )
            item = await self._require_item(uow, assignment, item_id)
            version = await uow.knowledge_article_versions.get_by_id(item.article_version_id)
            if version is None:
                raise NotFoundError(f"Acknowledgement item {item_id} not found")
            if mark_opened and actor_employee_id == assignment.employee_id:
                await self._mark_in_progress(uow, assignment)
            await uow.commit()
            item.article_version = version
            return assignment, item, version

    async def acknowledge_item(
        self,
        assignment_id: UUID,
        item_id: UUID,
        *,
        company_id: UUID,
        employee_id: UUID,
    ) -> tuple[Assignment, AssignmentAcknowledgementItem, list[AssignmentAcknowledgementItem]]:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            assignment = await self._require_acknowledgement_assignment(
                uow, assignment_id, company_id
            )
            if assignment.employee_id != employee_id:
                raise NotFoundError(f"Assignment {assignment_id} not found")
            item = await self._require_item(uow, assignment, item_id)
            if assignment.status == AssignmentStatus.CANCELLED.value:
                raise ValidationError("Cannot acknowledge a cancelled assignment")
            if assignment.status == AssignmentStatus.COMPLETED.value:
                if item.acknowledged_at is not None:
                    items = await uow.assignment_acknowledgement_items.list_by_assignment_id(
                        assignment_id
                    )
                    await uow.commit()
                    return assignment, item, items
                raise ValidationError("Completed assignment cannot be acknowledged")
            if assignment.status not in _OPEN_STATUSES:
                raise ValidationError("Assignment is not active")

            now = datetime.now(UTC)
            await self._mark_in_progress(uow, assignment, now=now)
            if item.acknowledged_at is None:
                updated = await uow.assignment_acknowledgement_items.update(
                    item.id,
                    acknowledged_at=now,
                )
                assert updated is not None
                item = updated
            items = await uow.assignment_acknowledgement_items.list_by_assignment_id(
                assignment_id
            )
            for row in items:
                if row.id == item.id:
                    item = row
                    break
            required_done = all(
                row.acknowledged_at is not None for row in items if row.is_required
            )
            if required_done and assignment.status != AssignmentStatus.COMPLETED.value:
                completed = await uow.assignments.update(
                    assignment.id,
                    status=AssignmentStatus.COMPLETED.value,
                    completed_at=now,
                )
                assert completed is not None
                assignment = completed
            await uow.commit()
            return assignment, item, items

    async def _validate_shared_assignment_inputs(
        self,
        uow: UnitOfWork,
        *,
        company_id: UUID,
        recipients: list[Employee],
        assigned_by_id: UUID | None,
        priority: str,
        deadline_overrides: dict[UUID, datetime | None],
    ) -> None:
        if priority not in _VALID_PRIORITIES:
            raise ValidationError(f"Invalid assignment priority {priority!r}")
        recipient_ids = {employee.id for employee in recipients}
        unknown_overrides = [
            emp_id for emp_id in deadline_overrides if emp_id not in recipient_ids
        ]
        if unknown_overrides:
            raise ValidationError(
                "deadline_overrides may only include resolved recipients"
            )
        if assigned_by_id is not None:
            assigner = await uow.employees.get_by_id(assigned_by_id)
            if assigner is None:
                raise NotFoundError(f"Employee {assigned_by_id} not found")
            ensure_same_company(
                resource_company_id=assigner.company_id,
                actor_company_id=company_id,
                not_found_message=f"Employee {assigned_by_id} not found",
            )
            if any(assigner.company_id != employee.company_id for employee in recipients):
                raise ValidationError("Assigner must belong to the same company")

    async def _resolve_acknowledgement_documents(
        self,
        uow: UnitOfWork,
        *,
        company_id: UUID,
        documents: list[AcknowledgementDocumentInput],
    ) -> list[tuple[AcknowledgementDocumentInput, KnowledgeArticleVersion]]:
        if not documents:
            raise ValidationError("documents are required for acknowledgement assignments")
        articles = await uow.knowledge_articles.list_by_ids(
            [item.article_id for item in documents]
        )
        by_id: dict[UUID, KnowledgeArticle] = {article.id: article for article in articles}
        resolved: list[tuple[AcknowledgementDocumentInput, KnowledgeArticleVersion]] = []
        for spec in sorted(documents, key=lambda item: item.position):
            article = by_id.get(spec.article_id)
            if article is None:
                raise NotFoundError(f"Knowledge article {spec.article_id} not found")
            ensure_same_company(
                resource_company_id=article.company_id,
                actor_company_id=company_id,
                not_found_message=f"Knowledge article {spec.article_id} not found",
            )
            if article.status != KnowledgeArticleStatus.PUBLISHED.value:
                raise ValidationError(
                    "Only published documents can be assigned for acknowledgement"
                )
            version = article.current_version
            if version is None or article.current_version_id is None:
                raise ValidationError(
                    "Published document is missing a current version"
                )
            if version.article_id != article.id or version.company_id != company_id:
                raise ValidationError("Document version does not belong to the article")
            resolved.append((spec, version))
        return resolved

    async def _require_acknowledgement_assignment(
        self,
        uow: UnitOfWork,
        assignment_id: UUID,
        company_id: UUID,
    ) -> Assignment:
        assignment = await uow.assignments.get_by_id(assignment_id)
        if assignment is None:
            raise NotFoundError(f"Assignment {assignment_id} not found")
        ensure_same_company(
            resource_company_id=assignment.company_id,
            actor_company_id=company_id,
            not_found_message=f"Assignment {assignment_id} not found",
        )
        if assignment.assignment_type != AssignmentType.ACKNOWLEDGEMENT.value:
            raise ValidationError("Assignment is not an acknowledgement assignment")
        return assignment

    async def _require_item(
        self,
        uow: UnitOfWork,
        assignment: Assignment,
        item_id: UUID,
    ) -> AssignmentAcknowledgementItem:
        item = await uow.assignment_acknowledgement_items.get_by_id_with_version(item_id)
        if item is None or item.assignment_id != assignment.id:
            raise NotFoundError(f"Acknowledgement item {item_id} not found")
        ensure_same_company(
            resource_company_id=item.company_id,
            actor_company_id=assignment.company_id,
            not_found_message=f"Acknowledgement item {item_id} not found",
        )
        return item

    async def _mark_in_progress(
        self,
        uow: UnitOfWork,
        assignment: Assignment,
        *,
        now: datetime | None = None,
    ) -> Assignment:
        if assignment.status != AssignmentStatus.PENDING.value:
            return assignment
        clock = now or datetime.now(UTC)
        updated = await uow.assignments.update(
            assignment.id,
            status=AssignmentStatus.IN_PROGRESS.value,
            started_at=assignment.started_at or clock,
        )
        assert updated is not None
        return updated

