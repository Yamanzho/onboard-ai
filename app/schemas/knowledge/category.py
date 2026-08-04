from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CategoryCreate(BaseModel):
    """Payload for creating a knowledge category."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "company_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "name": "Company Policies",
                    "slug": "company-policies",
                    "position": 0,
                }
            ]
        }
    )

    company_id: UUID = Field(description="Tenant company that owns the category.")
    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="URL-safe slug; derived from name when omitted.",
    )
    parent_id: UUID | None = Field(
        default=None,
        description="Optional parent category within the same company.",
    )
    position: int = Field(default=0, ge=0)


class CategoryUpdate(BaseModel):
    """Partial category update. At least one field is required."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    parent_id: UUID | None = None
    position: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "CategoryUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class CategoryResponse(BaseModel):
    """Knowledge category resource."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    parent_id: UUID | None
    name: str
    slug: str
    position: int
    created_at: datetime
    updated_at: datetime
