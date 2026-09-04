from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DepartmentCreate(BaseModel):
    """Payload for creating a department."""

    company_id: UUID = Field(description="Tenant company that owns the department.")
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


class DepartmentUpdate(BaseModel):
    """Partial department update. At least one field is required."""

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
    def require_at_least_one_field(self) -> "DepartmentUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class DepartmentSummary(BaseModel):
    """Compact department reference nested on employees and topics."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    is_active: bool


class DepartmentResponse(BaseModel):
    """Department resource."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
