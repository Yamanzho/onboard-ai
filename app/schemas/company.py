from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.limits import (
    MAX_COMPANY_SETTINGS_JSON_BYTES,
    ensure_json_object_within_limit,
)


class CompanyCreate(BaseModel):
    """Payload for creating a company."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Acme Corp",
                    "slug": "acme",
                    "timezone": "UTC",
                    "settings": {"locale": "en"},
                }
            ]
        }
    )

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Display name of the company.",
    )
    slug: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="URL-safe unique identifier (lowercase, digits, hyphens).",
    )
    timezone: str = Field(
        default="UTC",
        min_length=1,
        max_length=64,
        description="IANA timezone used for scheduling and deadlines.",
    )
    settings: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arbitrary company settings (feature flags, locale, etc.); "
            f"max {MAX_COMPANY_SETTINGS_JSON_BYTES} serialized UTF-8 bytes."
        ),
    )

    @field_validator("settings")
    @classmethod
    def limit_settings_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        return ensure_json_object_within_limit(
            value,
            max_bytes=MAX_COMPANY_SETTINGS_JSON_BYTES,
            field_name="settings",
        )


class CompanyUpdate(BaseModel):
    """Partial update payload for the caller's own company profile.

    Tenant activation (``is_active``) is intentionally omitted — lifecycle
    changes are platform-only via Super Admin APIs.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Acme Corporation",
                    "timezone": "Europe/Berlin",
                }
            ]
        }
    )

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="New display name.",
    )
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="New unique slug.",
    )
    timezone: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="New IANA timezone.",
    )
    settings: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Replacement settings object; "
            f"max {MAX_COMPANY_SETTINGS_JSON_BYTES} serialized UTF-8 bytes."
        ),
    )

    @field_validator("settings")
    @classmethod
    def limit_settings_size(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return value
        return ensure_json_object_within_limit(
            value,
            max_bytes=MAX_COMPANY_SETTINGS_JSON_BYTES,
            field_name="settings",
        )

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "CompanyUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class CompanyResponse(BaseModel):
    """Company resource returned by the API."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "name": "Acme Corp",
                    "slug": "acme",
                    "timezone": "UTC",
                    "is_active": True,
                    "settings": {"locale": "en"},
                    "created_at": "2026-08-04T12:00:00Z",
                    "updated_at": "2026-08-04T12:00:00Z",
                }
            ]
        },
    )

    id: UUID = Field(description="Company unique identifier.")
    name: str = Field(description="Display name of the company.")
    slug: str = Field(description="URL-safe unique identifier.")
    timezone: str = Field(description="IANA timezone.")
    is_active: bool = Field(description="Whether the company tenant is active.")
    settings: dict[str, Any] = Field(description="Company settings JSON object.")
    created_at: datetime = Field(description="Creation timestamp (UTC).")
    updated_at: datetime = Field(description="Last update timestamp (UTC).")


class ErrorResponse(BaseModel):
    """Standard error body for documented HTTP errors."""

    detail: str = Field(description="Human-readable error description.")
