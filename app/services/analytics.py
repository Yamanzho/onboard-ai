from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import case, cast, func, select
from sqlalchemy.sql import Select
from sqlalchemy.types import Date

from app.core import capabilities as capability_catalog
from app.core.capabilities import VisibilityScope
from app.core.exceptions import NotFoundError
from app.db.enums import (
    AssignmentPriority,
    AssignmentStatus,
    AssignmentType,
    EmployeeRole,
    EmployeeStatus,
    ProgressStatus,
)
from app.db.models.assignment import Assignment
from app.db.models.employee import Employee
from app.db.models.onboarding_program import OnboardingProgram
from app.db.models.progress import Progress
from app.db.uow import UnitOfWork
from app.schemas.analytics import (
    AssignmentAnalyticsResponse,
    AssignmentAnalyticsSlice,
    CompletionByProgram,
    CompletionOverTimePoint,
    OnboardingAnalyticsResponse,
)
from app.services.tenancy import ensure_same_company

_ACTIVE = (
    AssignmentStatus.PENDING.value,
    AssignmentStatus.IN_PROGRESS.value,
)
_COUNTABLE = (
    AssignmentStatus.PENDING.value,
    AssignmentStatus.IN_PROGRESS.value,
    AssignmentStatus.COMPLETED.value,
)
_LOOKBACK_DAYS = 90


def _completion_rate_percent(completed: int, pending: int, in_progress: int) -> float | None:
    """completed / (completed + pending + in_progress) as 0-100. Cancelled excluded."""
    denominator = completed + pending + in_progress
    if denominator <= 0:
        return None
    return round(completed * 100.0 / denominator, 1)


def _apply_assignment_scope(
    stmt: Select,
    *,
    company_id: UUID,
    department_id: UUID | None,
    assignment_type: str | None,
    already_joined_employee: bool = False,
) -> Select:
    stmt = stmt.where(Assignment.company_id == company_id)
    if department_id is not None:
        if not already_joined_employee:
            stmt = stmt.join(Employee, Employee.id == Assignment.employee_id)
        stmt = stmt.where(Employee.department_id == department_id)
    if assignment_type is not None:
        stmt = stmt.where(Assignment.assignment_type == assignment_type)
    return stmt


class AnalyticsService:
    """Tenant onboarding metrics from existing assignment/progress/employee rows."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    def _resolve_analytics_scope(
        self,
        actor: Employee,
        requested_department_id: UUID | None,
    ) -> tuple[VisibilityScope, UUID | None]:
        if not capability_catalog.has_capability(
            actor, capability_catalog.Capability.ANALYTICS_VIEW
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        scope = capability_catalog.analytics_visibility_scope(actor)
        if scope in {VisibilityScope.OWN, VisibilityScope.NONE}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Analytics requires department or company visibility",
            )
        try:
            department_id = capability_catalog.scoped_department_id(
                actor, scope, requested_department_id
            )
        except capability_catalog.ScopeDeniedError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            ) from exc
        return scope, department_id

    async def get_onboarding_analytics(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        actor: Employee | None = None,
        department_id: UUID | None = None,
    ) -> OnboardingAnalyticsResponse:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        scoped_department_id = department_id
        if actor is not None:
            _scope, scoped_department_id = self._resolve_analytics_scope(
                actor, department_id
            )
            if _scope is VisibilityScope.DEPARTMENT and scoped_department_id is None:
                return self._empty_onboarding()

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            session = uow.session

            employee_stmt = select(func.count()).select_from(Employee).where(
                Employee.company_id == company_id,
                Employee.role == EmployeeRole.EMPLOYEE.value,
                Employee.status != EmployeeStatus.ARCHIVED.value,
            )
            if scoped_department_id is not None:
                employee_stmt = employee_stmt.where(
                    Employee.department_id == scoped_department_id
                )
            total_employees = int(await session.scalar(employee_stmt) or 0)

            async def _count_assignments(*statuses: str) -> int:
                stmt = select(func.count()).select_from(Assignment)
                stmt = _apply_assignment_scope(
                    stmt,
                    company_id=company_id,
                    department_id=scoped_department_id,
                    assignment_type=None,
                )
                stmt = stmt.where(Assignment.status.in_(statuses))
                return int(await session.scalar(stmt) or 0)

            active_onboarding = await _count_assignments(*_ACTIVE)
            completed_onboarding = await _count_assignments(
                AssignmentStatus.COMPLETED.value
            )
            cancelled = await _count_assignments(AssignmentStatus.CANCELLED.value)
            countable = active_onboarding + completed_onboarding
            completion_rate = (
                round(completed_onboarding / countable, 4) if countable else None
            )

            pct_stmt = (
                select(
                    Progress.assignment_id,
                    (
                        func.sum(
                            case(
                                (Progress.status == ProgressStatus.COMPLETED.value, 1),
                                else_=0,
                            )
                        )
                        * 100.0
                        / func.nullif(func.count(), 0)
                    ).label("pct"),
                )
                .join(Assignment, Assignment.id == Progress.assignment_id)
            )
            pct_stmt = _apply_assignment_scope(
                pct_stmt,
                company_id=company_id,
                department_id=scoped_department_id,
                assignment_type=None,
            )
            pct_stmt = pct_stmt.where(
                Assignment.status != AssignmentStatus.CANCELLED.value,
            ).group_by(Progress.assignment_id)
            pct_sub = pct_stmt.subquery()
            average_progress = await session.scalar(select(func.avg(pct_sub.c.pct)))

            async def _distinct_employees(status: str) -> int:
                stmt = select(func.count(func.distinct(Assignment.employee_id)))
                stmt = _apply_assignment_scope(
                    stmt,
                    company_id=company_id,
                    department_id=scoped_department_id,
                    assignment_type=None,
                )
                stmt = stmt.where(Assignment.status == status)
                return int(await session.scalar(stmt) or 0)

            employees_not_started = await _distinct_employees(
                AssignmentStatus.PENDING.value
            )
            employees_in_progress = await _distinct_employees(
                AssignmentStatus.IN_PROGRESS.value
            )
            employees_completed = await _distinct_employees(
                AssignmentStatus.COMPLETED.value
            )

            program_stmt = (
                select(
                    Assignment.program_id,
                    OnboardingProgram.title,
                    func.count().label("assigned"),
                    func.sum(
                        case(
                            (
                                Assignment.status
                                == AssignmentStatus.COMPLETED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ).label("completed"),
                )
                .join(
                    OnboardingProgram,
                    OnboardingProgram.id == Assignment.program_id,
                )
            )
            program_stmt = _apply_assignment_scope(
                program_stmt,
                company_id=company_id,
                department_id=scoped_department_id,
                assignment_type=None,
            )
            program_stmt = (
                program_stmt.where(
                    Assignment.status != AssignmentStatus.CANCELLED.value,
                )
                .group_by(Assignment.program_id, OnboardingProgram.title)
                .order_by(OnboardingProgram.title)
            )
            program_rows = (await session.execute(program_stmt)).all()
            by_program: list[CompletionByProgram] = []
            for program_id, title, assigned, completed in program_rows:
                assigned_n = int(assigned or 0)
                completed_n = int(completed or 0)
                by_program.append(
                    CompletionByProgram(
                        program_id=program_id,
                        title=title,
                        assigned=assigned_n,
                        completed=completed_n,
                        completion_rate=(
                            round(completed_n / assigned_n, 4) if assigned_n else None
                        ),
                    )
                )

            since = datetime.now(UTC) - timedelta(days=_LOOKBACK_DAYS)
            time_stmt = select(
                cast(Assignment.completed_at, Date).label("day"),
                func.count().label("count"),
            )
            time_stmt = _apply_assignment_scope(
                time_stmt,
                company_id=company_id,
                department_id=scoped_department_id,
                assignment_type=None,
            )
            time_stmt = (
                time_stmt.where(
                    Assignment.status == AssignmentStatus.COMPLETED.value,
                    Assignment.completed_at.is_not(None),
                    Assignment.completed_at >= since,
                )
                .group_by(cast(Assignment.completed_at, Date))
                .order_by(cast(Assignment.completed_at, Date))
            )
            time_rows = (await session.execute(time_stmt)).all()
            completed_over_time = [
                CompletionOverTimePoint(date=str(day), count=int(count))
                for day, count in time_rows
                if day is not None
            ]

            now = datetime.now(UTC)
            overdue_stmt = select(func.count()).select_from(Assignment)
            overdue_stmt = _apply_assignment_scope(
                overdue_stmt,
                company_id=company_id,
                department_id=scoped_department_id,
                assignment_type=None,
            )
            overdue_stmt = overdue_stmt.where(
                Assignment.status.in_(_ACTIVE),
                Assignment.due_at.is_not(None),
                Assignment.due_at < now,
            )
            overdue_count = int(await session.scalar(overdue_stmt) or 0)
            by_priority: dict[str, int] = {}
            for priority in AssignmentPriority:
                pri_stmt = select(func.count()).select_from(Assignment)
                pri_stmt = _apply_assignment_scope(
                    pri_stmt,
                    company_id=company_id,
                    department_id=scoped_department_id,
                    assignment_type=None,
                )
                pri_stmt = pri_stmt.where(
                    Assignment.status.in_(_ACTIVE),
                    Assignment.priority == priority.value,
                )
                by_priority[priority.value] = int(await session.scalar(pri_stmt) or 0)

            return OnboardingAnalyticsResponse(
                total_employees=total_employees,
                active_onboarding=active_onboarding,
                completed_onboarding=completed_onboarding,
                cancelled_onboarding=cancelled,
                completion_rate=completion_rate,
                average_progress=(
                    round(float(average_progress), 2)
                    if average_progress is not None
                    else None
                ),
                employees_not_started=employees_not_started,
                employees_in_progress=employees_in_progress,
                employees_completed=employees_completed,
                by_program=by_program,
                completed_over_time=completed_over_time,
                overdue_count=overdue_count,
                by_priority=by_priority,
            )

    async def get_assignment_analytics(
        self,
        company_id: UUID,
        *,
        actor: Employee,
        department_id: UUID | None = None,
        assignment_type: str | None = None,
    ) -> AssignmentAnalyticsResponse:
        """SQL-aggregated operational assignment metrics. Scope is mandatory."""
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor.company_id,
            not_found_message=f"Company {company_id} not found",
        )
        if assignment_type is not None and assignment_type not in {
            item.value for item in AssignmentType
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid assignment type",
            )
        scope, scoped_department_id = self._resolve_analytics_scope(
            actor, department_id
        )
        response_scope = (
            VisibilityScope.DEPARTMENT.value
            if scope is VisibilityScope.DEPARTMENT
            else VisibilityScope.ALL.value
        )
        if scope is VisibilityScope.DEPARTMENT and scoped_department_id is None:
            return self._empty_assignment_analytics(
                scope=response_scope,
                department_id=None,
                assignment_type=assignment_type,
            )

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            session = uow.session
            now = datetime.now(UTC)

            overall = await self._assignment_slice(
                session,
                company_id=company_id,
                department_id=scoped_department_id,
                assignment_type=assignment_type,
                now=now,
            )
            by_type: dict[str, AssignmentAnalyticsSlice] = {}
            if assignment_type is None:
                for item in AssignmentType:
                    by_type[item.value] = await self._assignment_slice(
                        session,
                        company_id=company_id,
                        department_id=scoped_department_id,
                        assignment_type=item.value,
                        now=now,
                    )
            by_priority: dict[str, int] = {}
            for priority in AssignmentPriority:
                stmt = select(func.count()).select_from(Assignment)
                stmt = _apply_assignment_scope(
                    stmt,
                    company_id=company_id,
                    department_id=scoped_department_id,
                    assignment_type=assignment_type,
                )
                stmt = stmt.where(
                    Assignment.status.in_(_ACTIVE),
                    Assignment.priority == priority.value,
                )
                by_priority[priority.value] = int(await session.scalar(stmt) or 0)

            return AssignmentAnalyticsResponse(
                active=overall.active,
                overdue=overall.overdue,
                completed=overall.completed,
                completion_rate=overall.completion_rate,
                employees_with_active=overall.employees_with_active,
                employees_with_overdue=overall.employees_with_overdue,
                scope=response_scope,
                department_id=scoped_department_id,
                assignment_type=assignment_type,
                by_type=by_type,
                by_priority=by_priority,
            )

    async def _assignment_slice(
        self,
        session,
        *,
        company_id: UUID,
        department_id: UUID | None,
        assignment_type: str | None,
        now: datetime,
    ) -> AssignmentAnalyticsSlice:
        async def _count(statuses: tuple[str, ...], *, overdue_only: bool = False) -> int:
            stmt = select(func.count()).select_from(Assignment)
            stmt = _apply_assignment_scope(
                stmt,
                company_id=company_id,
                department_id=department_id,
                assignment_type=assignment_type,
            )
            stmt = stmt.where(Assignment.status.in_(statuses))
            if overdue_only:
                stmt = stmt.where(
                    Assignment.due_at.is_not(None),
                    Assignment.due_at < now,
                )
            return int(await session.scalar(stmt) or 0)

        async def _distinct(statuses: tuple[str, ...], *, overdue_only: bool = False) -> int:
            stmt = select(func.count(func.distinct(Assignment.employee_id)))
            stmt = _apply_assignment_scope(
                stmt,
                company_id=company_id,
                department_id=department_id,
                assignment_type=assignment_type,
            )
            stmt = stmt.where(Assignment.status.in_(statuses))
            if overdue_only:
                stmt = stmt.where(
                    Assignment.due_at.is_not(None),
                    Assignment.due_at < now,
                )
            return int(await session.scalar(stmt) or 0)

        pending = await _count((AssignmentStatus.PENDING.value,))
        in_progress = await _count((AssignmentStatus.IN_PROGRESS.value,))
        completed = await _count((AssignmentStatus.COMPLETED.value,))
        active = pending + in_progress
        overdue = await _count(_ACTIVE, overdue_only=True)
        return AssignmentAnalyticsSlice(
            active=active,
            overdue=overdue,
            completed=completed,
            completion_rate=_completion_rate_percent(completed, pending, in_progress),
            employees_with_active=await _distinct(_ACTIVE),
            employees_with_overdue=await _distinct(_ACTIVE, overdue_only=True),
        )

    @staticmethod
    def _empty_onboarding() -> OnboardingAnalyticsResponse:
        return OnboardingAnalyticsResponse(
            total_employees=0,
            active_onboarding=0,
            completed_onboarding=0,
            cancelled_onboarding=0,
            completion_rate=None,
            average_progress=None,
            employees_not_started=0,
            employees_in_progress=0,
            employees_completed=0,
        )

    @staticmethod
    def _empty_assignment_analytics(
        *,
        scope: str,
        department_id: UUID | None,
        assignment_type: str | None,
    ) -> AssignmentAnalyticsResponse:
        empty = AssignmentAnalyticsSlice()
        by_type = {
            item.value: AssignmentAnalyticsSlice() for item in AssignmentType
        }
        return AssignmentAnalyticsResponse(
            **empty.model_dump(),
            scope=scope,
            department_id=department_id,
            assignment_type=assignment_type,
            by_type=by_type if assignment_type is None else {},
            by_priority={item.value: 0 for item in AssignmentPriority},
        )
