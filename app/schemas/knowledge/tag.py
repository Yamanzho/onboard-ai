from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TagCreate(BaseModel):
    """Payload for creating a company-scoped knowledge tag."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "company_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "name": "Security",
                    "slug": "security",
                }
            ]
        }
    )

    company_id: UUID = Field(description="Tenant company that owns the tag.")
    name: str = Field(..., min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="URL-safe slug; derived from name when omitted.",
    )


class TagUpdate(BaseModel):
    """Partial tag update. At least one field is required."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "TagUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class TagResponse(BaseModel):
    """Knowledge tag resource."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    name: str
    slug: str
    created_at: datetime
    updated_at: datetime
