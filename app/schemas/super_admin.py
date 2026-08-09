from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.limits import (
    MAX_COMPANY_SETTINGS_JSON_BYTES,
    ensure_json_object_within_limit,
)

CompanyAdminRoleLiteral = Literal["admin", "hr", "employee"]
SubscriptionTierLiteral = Literal["starter", "professional", "enterprise"]
SubscriptionStatusLiteral = Literal["trial", "active", "suspended", "expired", "blocked"]
PaymentStatusLiteral = Literal["unpaid", "paid", "past_due"]


class SuperAdminLoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class SuperAdminResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str
    role: str = Field(default="super_admin")
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PlatformDashboardStats(BaseModel):
    companies_count: int
    active_companies: int
    trial_companies: int
    expired_companies: int
    employees_count: int
    active_assignments_count: int


class CompanySubscriptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    tier: str
    status: str
    payment_status: str
    started_at: datetime
    ends_at: datetime | None
    auto_renew: bool
    employee_limit: int
    program_limit: int
    is_current: bool
    created_at: datetime
    updated_at: datetime


class CompanySubscriptionUpdate(BaseModel):
    tier: SubscriptionTierLiteral | None = None
    status: SubscriptionStatusLiteral | None = None
    payment_status: PaymentStatusLiteral | None = None
    started_at: datetime | None = None
    ends_at: datetime | None = None
    auto_renew: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "CompanySubscriptionUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class SubscriptionHistoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    subscription_id: UUID | None
    event_type: str
    previous_status: str | None
    new_status: str | None
    previous_tier: str | None
    new_tier: str | None
    note: str | None
    created_at: datetime


class CompanyLimitsResponse(BaseModel):
    company_id: UUID
    employee_limit: int
    employees_used: int
    program_limit: int
    programs_used: int


class SuperAdminCompanyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    settings: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            f"Company settings; max {MAX_COMPANY_SETTINGS_JSON_BYTES} serialized UTF-8 bytes."
        ),
    )
    description: str | None = None
    logo_url: str | None = Field(default=None, max_length=2048)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=64)
    contact_person: str | None = Field(default=None, max_length=255)
    admin_full_name: str = Field(..., min_length=1, max_length=255)
    admin_email: str = Field(..., min_length=3, max_length=320)
    admin_telegram_user_id: int = Field(..., gt=0)

    @field_validator("settings")
    @classmethod
    def limit_settings_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        return ensure_json_object_within_limit(
            value,
            max_bytes=MAX_COMPANY_SETTINGS_JSON_BYTES,
            field_name="settings",
        )

    @field_validator("admin_email")
    @classmethod
    def normalize_admin_email(cls, value: str) -> str:
        return value.strip().lower()


class SuperAdminCompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    is_active: bool | None = None
    settings: dict[str, Any] | None = Field(
        default=None,
        description=(
            f"Company settings; max {MAX_COMPANY_SETTINGS_JSON_BYTES} serialized UTF-8 bytes."
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
    def require_at_least_one_field(self) -> "SuperAdminCompanyUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class SuperAdminCompanyProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = None
    logo_url: str | None = Field(default=None, max_length=2048)
    contact_email: str | None = Field(default=None, max_length=320)
    contact_phone: str | None = Field(default=None, max_length=64)
    contact_person: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "SuperAdminCompanyProfileUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class SuperAdminCompanyDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    timezone: str
    is_active: bool
    settings: dict[str, Any]
    description: str | None = None
    logo_url: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    contact_person: str | None = None
    created_at: datetime
    updated_at: datetime
    employees_count: int = 0
    programs_count: int = 0
    assignments_count: int = 0
    subscription: CompanySubscriptionResponse | None = None
    limits: CompanyLimitsResponse | None = None


class PlatformUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    company_name: str | None = None
    company_slug: str | None = None
    full_name: str
    email: str | None
    role: str
    status: str
    telegram_user_id: int
    telegram_username: str | None
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PlatformUserUpdate(BaseModel):
    role: CompanyAdminRoleLiteral | None = None
    status: Literal["invited", "active", "archived"] | None = None

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "PlatformUserUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class CompanyUserCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=3, max_length=320)
    role: CompanyAdminRoleLiteral = "admin"
    telegram_user_id: int | None = Field(default=None, gt=0)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class InvitePreviewRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=256)


class InvitePreviewResponse(BaseModel):
    employee_id: UUID
    full_name: str
    email: str
    company_name: str | None
    expires_at: datetime


class InviteAcceptRequest(BaseModel):
    token: str = Field(..., min_length=10, max_length=256)
    password: str = Field(..., min_length=8, max_length=256)


class PlatformAuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    super_admin_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    company_id: UUID | None
    summary: str
    details: dict[str, Any]
    created_at: datetime


class PlatformSettingsResponse(BaseModel):
    maintenance_mode: bool = False
    allow_new_companies: bool = True
    default_timezone: str = "UTC"
    notes: str = "Platform settings stub — wire persistence in a later sprint."


class PlatformSettingsUpdate(BaseModel):
    maintenance_mode: bool | None = None
    allow_new_companies: bool | None = None
    default_timezone: str | None = Field(default=None, min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "PlatformSettingsUpdate":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self
