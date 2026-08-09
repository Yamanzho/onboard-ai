from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    telegram_user_id: int = Field(..., gt=0, description="Telegram user id (unique per company).")
    telegram_chat_id: int | None = Field(default=None, description="Optional Telegram chat id.")
    telegram_username: str | None = Field(default=None, max_length=255)
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320, description="Required when status=invited.")
    role: EmployeeRoleLiteral = Field(default="employee")
    status: EmployeeStatusLiteral = Field(default="invited")
    hired_at: date | None = Field(default=None, description="Optional hire date.")

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
    created_at: datetime
    updated_at: datetime
    # Invite delivery (set on create when status=invited).
    invite_email_sent: bool | None = None
    invite_delivery: InviteDeliveryLiteral | None = None
    invite_url: str | None = None
    invite_detail: str | None = None
    telegram_invite_url: str | None = None
