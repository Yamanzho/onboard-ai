from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.department import DepartmentSummary


class ManagerSummary(BaseModel):
    """Compact employee reference for manager / responsibility displays."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str
    job_title: str | None = None
    status: str


class TopicResponsibilityPayload(BaseModel):
    """Replace the single responsibility mapping for a topic."""

    department_id: UUID | None = None
    employee_id: UUID | None = None

    @model_validator(mode="after")
    def require_at_least_one_target(self) -> "TopicResponsibilityPayload":
        if self.department_id is None and self.employee_id is None:
            raise ValueError("department_id or employee_id is required")
        return self


class TopicResponsibilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    topic_id: UUID
    department_id: UUID | None
    employee_id: UUID | None
    department: DepartmentSummary | None = None
    employee: ManagerSummary | None = None
    created_at: datetime
    updated_at: datetime


class QuestionTopicCreate(BaseModel):
    company_id: UUID = Field(description="Tenant company that owns the topic.")
    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="URL-safe slug; derived from name when omitted.",
    )
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    department_id: UUID | None = Field(
        default=None,
        description="Optional responsible department set at create time.",
    )
    employee_id: UUID | None = Field(
        default=None,
        description="Optional responsible employee set at create time.",
    )


class QuestionTopicUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "QuestionTopicUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class QuestionTopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    responsibility: TopicResponsibilityResponse | None = None
    created_at: datetime
    updated_at: datetime
