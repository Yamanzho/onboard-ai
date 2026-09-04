from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import inspect as sa_inspect

from app.db.models.employee import Employee
from app.schemas.department import DepartmentSummary
from app.schemas.question_topic import ManagerSummary

EmployeeRoleLiteral = Literal["employee", "hr", "admin"]
EmployeeStatusLiteral = Literal["invited", "active", "archived"]
InviteDeliveryLiteral = Literal["email", "manual_url"]


class EmployeeCreate(BaseModel):
    """Payload for creating an employee under a company."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "company_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "telegram_user_id": 123456789,
                    "full_name": "Ada Lovelace",
                    "telegram_username": "ada",
                    "email": "ada@example.com",
                    "role": "employee",
                    "status": "invited",
                }
            ]
        }
    )

    company_id: UUID = Field(description="Company tenant the employee belongs to.")
    telegram_user_id: int | None = Field(
        default=None,
        gt=0,
        description=(
            "Telegram user id (unique per company). Optional for invited employees — "
            "a placeholder is assigned and overwritten when they open the Telegram invite."
        ),
    )
    telegram_chat_id: int | None = Field(default=None, description="Optional Telegram chat id.")
    telegram_username: str | None = Field(default=None, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320, description="Required when status=invited.")
    role: EmployeeRoleLiteral = Field(default="employee")
    status: EmployeeStatusLiteral = Field(default="invited")
    hired_at: date | None = Field(default=None, description="Optional hire date.")
    department_id: UUID | None = Field(
        default=None,
        description="Optional department in the same company.",
    )
    manager_id: UUID | None = Field(
        default=None,
        description="Optional manager in the same company.",
    )
    job_title: str | None = Field(
        default=None,
        max_length=255,
        description="Optional job title. Not a role/permission.",
    )

    @model_validator(mode="after")
    def require_email_when_invited(self) -> "EmployeeCreate":
        if self.status == "invited":
            if not self.email or not self.email.strip():
                raise ValueError("email is required when inviting an employee")
        return self


class EmployeeUpdate(BaseModel):
    """Partial employee update. At least one field is required."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"full_name": "Ada L.", "status": "active"}]
        }
    )

    telegram_user_id: int | None = Field(default=None, gt=0)
    telegram_chat_id: int | None = None
    telegram_username: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    role: EmployeeRoleLiteral | None = None
    status: EmployeeStatusLiteral | None = None
    hired_at: date | None = None
    department_id: UUID | None = None
    manager_id: UUID | None = None
    job_title: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "EmployeeUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class EmployeeResponse(BaseModel):
    """Employee resource returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    telegram_user_id: int
    telegram_chat_id: int | None
    telegram_username: str | None
    full_name: str
    email: str | None
    role: str
    status: str
    hired_at: date | None
    department_id: UUID | None = None
    manager_id: UUID | None = None
    job_title: str | None = None
    department: DepartmentSummary | None = None
    manager: ManagerSummary | None = None
    created_at: datetime
    updated_at: datetime
    # Invite delivery (set on create when status=invited).
    invite_email_sent: bool | None = None
    invite_delivery: InviteDeliveryLiteral | None = None
    invite_url: str | None = None
    invite_detail: str | None = None
    telegram_invite_url: str | None = None


InviteHistoryStatusLiteral = Literal["active", "used", "expired"]
OnboardingInvitePurposeLiteral = Literal["employee", "hr", "admin"]


class EmployeeInviteHistoryItem(BaseModel):
    """Onboarding invite metadata for admin history — never includes secrets."""

    id: UUID
    purpose: OnboardingInvitePurposeLiteral
    status: InviteHistoryStatusLiteral
    invited_email: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None


class EmployeeInviteHistoryResponse(BaseModel):
    items: list[EmployeeInviteHistoryItem]


def employee_to_response(employee: Employee) -> EmployeeResponse:
    """Build an employee payload without triggering unloaded relationship IO.

    Nested department/manager summaries are included only when those
    relationships were eager-loaded in the current session.
    """
    state = sa_inspect(employee)
    department = (
        employee.department if "department" not in state.unloaded else None
    )
    manager = employee.manager if "manager" not in state.unloaded else None
    return EmployeeResponse(
        id=employee.id,
        company_id=employee.company_id,
        telegram_user_id=employee.telegram_user_id,
        telegram_chat_id=employee.telegram_chat_id,
        telegram_username=employee.telegram_username,
        full_name=employee.full_name,
        email=employee.email,
        role=employee.role,
        status=employee.status,
        hired_at=employee.hired_at,
        department_id=employee.department_id,
        manager_id=employee.manager_id,
        job_title=employee.job_title,
        department=(
            DepartmentSummary.model_validate(department)
            if department is not None
            else None
        ),
        manager=(
            ManagerSummary.model_validate(manager) if manager is not None else None
        ),
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )
