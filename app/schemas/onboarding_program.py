from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProgramCreate(BaseModel):
    """Payload for creating an onboarding program (draft)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "company_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "title": "Engineering Onboarding",
                    "description": "First 30 days for new engineers",
                }
            ]
        }
    )

    company_id: UUID = Field(description="Tenant company that owns the program.")
    title: str = Field(..., min_length=1, max_length=255, description="Program title.")
    description: str | None = Field(
        default=None,
        max_length=5000,
        description="Optional program description.",
    )


class ProgramUpdate(BaseModel):
    """Partial update for program metadata (not publish/archive state)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"title": "Engineering Onboarding v2"}]
        }
    )

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5000)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "ProgramUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class ProgramResponse(BaseModel):
    """Onboarding program resource."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    title: str
    description: str | None
    is_active: bool = Field(description="True when published; False for draft/archived.")
    revision: int = Field(
        default=1,
        description="Course structure/content generation. Starts at 1.",
    )
    structure_locked: bool = Field(
        default=False,
        description=(
            "True when pending or in_progress assignments exist. "
            "Structure and training content cannot be edited."
        ),
    )
    can_edit_structure: bool = Field(
        default=True,
        description="False when structure_locked is true.",
    )
    created_at: datetime
    updated_at: datetime
