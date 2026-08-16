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
