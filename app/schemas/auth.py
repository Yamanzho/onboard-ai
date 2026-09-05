from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TokenResponse(BaseModel):
    """JWT token pair returned by bot/service auth flows."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                    "token_type": "bearer",
                }
            ]
        }
    )

    access_token: str = Field(description="Short-lived JWT access token.")
    refresh_token: str = Field(description="Opaque refresh token.")
    token_type: str = Field(default="bearer", description="Always 'bearer'.")


class BrowserSessionResponse(BaseModel):
    """Cookie-only browser auth acknowledgement (no raw tokens in JSON)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "token_type": "bearer",
                }
            ]
        }
    )

    token_type: str = Field(default="bearer", description="Always 'bearer'.")


class RefreshRequest(BaseModel):
    """Refresh token payload (optional when httpOnly cookie is present)."""

    refresh_token: str | None = Field(
        default=None,
        description="Opaque refresh token from login (or omit and use cookie).",
    )


class CurrentUserResponse(BaseModel):
    """Authenticated employee profile from the access token."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    full_name: str
    email: str | None
    role: str = Field(description="One of: admin, hr, employee.")
    status: str
    telegram_user_id: int
    telegram_username: str | None
    telegram_connected: bool = False
    company_name: str | None = None
    company_description: str | None = None
    hired_at: date | None = None
    department_id: UUID | None = None
    manager_id: UUID | None = None
    job_title: str | None = None
    capabilities: list[str] = Field(
        default_factory=list,
        description="Effective capabilities resolved server-side from the role.",
    )
    created_at: datetime
    updated_at: datetime


class ProfileUpdateRequest(BaseModel):
    """Self-service profile update — only personal fields allowed."""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "ProfileUpdateRequest":
        if not self.model_dump(exclude_unset=True):
            raise ValueError("At least one field must be provided for update")
        return self


class BotTelegramLoginRequest(BaseModel):
    """Telegram identity exchange request from the bot service."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "telegram_user_id": 123456789,
                }
            ]
        },
        extra="forbid",
    )

    telegram_user_id: int = Field(
        gt=0,
        description="Telegram user id of the employee to authenticate.",
    )
    company_id: UUID | None = Field(
        default=None,
        description=(
            "Ignored. Kept for older bot clients. Tenant is derived from the "
            "bound employee record, never from this field."
        ),
    )


class BotInviteAcceptRequest(BaseModel):
    """Accept an EMPLOYEE invite by binding Telegram identity (bot only)."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=10, max_length=256)
    telegram_user_id: int = Field(..., gt=0)
    telegram_username: str | None = Field(default=None, max_length=255)
    telegram_chat_id: int | None = None
    company_id: UUID | None = Field(
        default=None,
        description=(
            "Ignored. Kept for older bot clients. Company comes from the invite."
        ),
    )


class BotTelegramLoginResponse(TokenResponse):
    """JWT pair plus the employee resolved from Telegram identity."""

    employee: CurrentUserResponse


class BotUpdateClaimRequest(BaseModel):
    """Internal bot request to claim one Telegram delivery."""

    model_config = ConfigDict(extra="forbid")

    update_id: int = Field(ge=0)
    update_type: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")


class BotUpdateClaimResponse(BaseModel):
    """Claim decision; ownership data is returned only to the bot service."""

    model_config = ConfigDict(extra="forbid")

    state: Literal["acquired", "completed", "processing"]
    receipt_id: UUID
    owner_token: UUID | None = None


class BotUpdateFinishRequest(BaseModel):
    """Internal ownership proof for completing or failing a claim."""

    model_config = ConfigDict(extra="forbid")

    receipt_id: UUID
    owner_token: UUID


class BotUpdateFinishResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updated: bool


class BotOutboundClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal[
        "ai_chat",
        "quiz_result",
        "assignment_initial",
        "assignment_reminder",
        "assignment_manual_reminder",
    ]
    source_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")


class BotOutboundBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=20, ge=1, le=20)


class BotOutboundDeliveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal[
        "acquired",
        "pending",
        "sending",
        "sent",
        "failed",
        "not_found",
    ]
    message_id: UUID | None = None
    owner_token: UUID | None = None
    chat_id: int | None = None
    source_type: Literal[
        "ai_chat",
        "quiz_result",
        "assignment_initial",
        "assignment_reminder",
        "assignment_manual_reminder",
    ] | None = None
    source_key: str | None = None
    body: str | None = None
    parse_mode: Literal["HTML"] | None = None
    attempt_count: int = 0
    telegram_message_id: int | None = None


class BotOutboundBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deliveries: list[BotOutboundDeliveryResponse]


class BotOutboundSentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    owner_token: UUID
    telegram_message_id: int = Field(gt=0)


class BotOutboundFailedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    owner_token: UUID
    retryable: bool
    error_category: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z0-9_]+$",
    )
    retry_after_seconds: int | None = Field(default=None, ge=0, le=3600)


class BotOutboundAllowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal[
        "ai_chat",
        "quiz_result",
        "assignment_initial",
        "assignment_reminder",
        "assignment_manual_reminder",
    ]
    source_key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9:_-]+$")


class PasswordChangeRequest(BaseModel):
    """Authenticated employee password change."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=256)
    confirm_password: str = Field(..., min_length=8, max_length=256)

    @model_validator(mode="after")
    def passwords_must_match(self) -> "PasswordChangeRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class PasswordResetPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=10, max_length=256)


class PasswordResetPreviewResponse(BaseModel):
    full_name: str
    email: str
    company_name: str | None
    expires_at: datetime
    purpose: Literal["password_reset"] = "password_reset"


class PasswordResetConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=10, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=256)
    confirm_password: str = Field(..., min_length=8, max_length=256)

    @model_validator(mode="after")
    def passwords_must_match(self) -> "PasswordResetConfirmRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class PasswordResetInitiateResponse(BaseModel):
    """Admin/HR-initiated password reset delivery status."""

    email_sent: bool
    delivery: Literal["email", "manual_url"]
    reset_url: str | None = None
    detail: str
