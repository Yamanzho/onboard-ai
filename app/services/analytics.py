from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import case, cast, func, select
from sqlalchemy.types import Date

from app.core.exceptions import NotFoundError
from app.db.enums import AssignmentStatus, EmployeeRole, EmployeeStatus, ProgressStatus
from app.db.models.assignment import Assignment
from app.db.models.employee import Employee
from app.db.models.onboarding_program import OnboardingProgram
from app.db.models.progress import Progress
from app.db.uow import UnitOfWork
from app.schemas.analytics import (
    CompletionByProgram,
    CompletionOverTimePoint,
    OnboardingAnalyticsResponse,
)
from app.services.tenancy import ensure_same_company

_ACTIVE = (
    AssignmentStatus.PENDING.value,
    AssignmentStatus.IN_PROGRESS.value,
)
_LOOKBACK_DAYS = 90


class AnalyticsService:
    """Tenant onboarding metrics from existing assignment/progress/employee rows."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def get_onboarding_analytics(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
    ) -> OnboardingAnalyticsResponse:
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
            session = uow.session

            total_employees = int(
                await session.scalar(
                    select(func.count())
                    .select_from(Employee)
                    .where(
                        Employee.company_id == company_id,
                        Employee.role == EmployeeRole.EMPLOYEE.value,
                        Employee.status != EmployeeStatus.ARCHIVED.value,
                    )
                )
                or 0
            )

            async def _count_assignments(*statuses: str) -> int:
                stmt = (
                    select(func.count())
                    .select_from(Assignment)
                    .where(
                        Assignment.company_id == company_id,
                        Assignment.status.in_(statuses),
                    )
                )
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

            pct_sub = (
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
                .where(
                    Assignment.company_id == company_id,
                    Assignment.status != AssignmentStatus.CANCELLED.value,
                )
                .group_by(Progress.assignment_id)
                .subquery()
            )
            average_progress = await session.scalar(select(func.avg(pct_sub.c.pct)))

            async def _distinct_employees(status: str) -> int:
                stmt = (
                    select(func.count(func.distinct(Assignment.employee_id)))
                    .where(
                        Assignment.company_id == company_id,
                        Assignment.status == status,
                    )
                )
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

            program_rows = (
                await session.execute(
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
                    .where(
                        Assignment.company_id == company_id,
                        Assignment.status != AssignmentStatus.CANCELLED.value,
                    )
                    .group_by(Assignment.program_id, OnboardingProgram.title)
                    .order_by(OnboardingProgram.title)
                )
            ).all()
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
            time_rows = (
                await session.execute(
                    select(
                        cast(Assignment.completed_at, Date).label("day"),
                        func.count().label("count"),
                    )
                    .where(
                        Assignment.company_id == company_id,
                        Assignment.status == AssignmentStatus.COMPLETED.value,
                        Assignment.completed_at.is_not(None),
                        Assignment.completed_at >= since,
                    )
                    .group_by(cast(Assignment.completed_at, Date))
                    .order_by(cast(Assignment.completed_at, Date))
                )
            ).all()
            completed_over_time = [
                CompletionOverTimePoint(date=str(day), count=int(count))
                for day, count in time_rows
                if day is not None
            ]

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
            )
