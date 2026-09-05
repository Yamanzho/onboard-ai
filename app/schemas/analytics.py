from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompletionByProgram(BaseModel):
    program_id: UUID
    title: str
    assigned: int
    completed: int
    completion_rate: float | None = Field(
        default=None,
        description="completed / assigned for non-cancelled assignments (0-1).",
    )


class CompletionOverTimePoint(BaseModel):
    date: str
    count: int


class OnboardingAnalyticsResponse(BaseModel):
    total_employees: int
    active_onboarding: int
    completed_onboarding: int
    cancelled_onboarding: int = 0
    completion_rate: float | None = None
    average_progress: float | None = None
    employees_not_started: int
    employees_in_progress: int
    employees_completed: int
    by_program: list[CompletionByProgram] = Field(default_factory=list)
    completed_over_time: list[CompletionOverTimePoint] = Field(default_factory=list)
    overdue_count: int = 0
    by_priority: dict[str, int] = Field(default_factory=dict)


class AssignmentAnalyticsSlice(BaseModel):
    """Counts for one assignment type or the overall scoped set."""

    active: int = 0
    overdue: int = 0
    completed: int = 0
    completion_rate: float | None = Field(
        default=None,
        description=(
            "Percent 0-100. completed / (completed + pending + in_progress). "
            "Cancelled assignments are excluded from the denominator."
        ),
    )
    employees_with_active: int = 0
    employees_with_overdue: int = 0


class AssignmentAnalyticsResponse(AssignmentAnalyticsSlice):
    """Operational assignment analytics. Always tenant-scoped; may be department-scoped."""

    scope: str = Field(description="all | department")
    department_id: UUID | None = None
    assignment_type: str | None = None
    by_type: dict[str, AssignmentAnalyticsSlice] = Field(default_factory=dict)
    by_priority: dict[str, int] = Field(default_factory=dict)


class CompanyAuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    actor_employee_id: UUID | None = None
    actor_name: str | None = None
    action: str
    resource_type: str
    resource_id: UUID | None = None
    summary: str
    details: dict = Field(default_factory=dict)
    created_at: datetime


class CompanyAuditLogListResponse(BaseModel):
    items: list[CompanyAuditLogResponse]
