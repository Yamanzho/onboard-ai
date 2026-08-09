from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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
    created_at: datetime
    updated_at: datetime


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
        }
    )

    company_id: UUID = Field(description="Tenant company ID (must match BOT_COMPANY_ID).")
    telegram_user_id: int = Field(
        gt=0,
        description="Telegram user id of the employee to authenticate.",
    )


class BotTelegramLoginResponse(TokenResponse):
    """JWT pair plus the employee resolved from Telegram identity."""

    employee: CurrentUserResponse


class PasswordChangeRequest(BaseModel):
    """Authenticated employee password change."""

    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=256)
