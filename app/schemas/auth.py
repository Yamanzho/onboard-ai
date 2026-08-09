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
                    "company_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                    "telegram_user_id": 123456789,
                }
            ]
        },
        extra="forbid",
    )

    company_id: UUID = Field(description="Tenant company ID (must match BOT_COMPANY_ID).")
    telegram_user_id: int = Field(
        gt=0,
        description="Telegram user id of the employee to authenticate.",
    )


class BotInviteAcceptRequest(BaseModel):
    """Accept an EMPLOYEE invite by binding Telegram identity (bot only)."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(..., min_length=10, max_length=256)
    telegram_user_id: int = Field(..., gt=0)
    telegram_username: str | None = Field(default=None, max_length=255)
    telegram_chat_id: int | None = None
    company_id: UUID = Field(description="Must match BOT_COMPANY_ID.")


class BotTelegramLoginResponse(TokenResponse):
    """JWT pair plus the employee resolved from Telegram identity."""

    employee: CurrentUserResponse


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
