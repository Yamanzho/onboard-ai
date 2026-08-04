from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID
import secrets

import jwt

from app.core.config import get_settings
from app.core.exceptions import AppError

TokenType = Literal["access", "refresh"]


class InvalidTokenError(AppError):
    """Raised when a JWT is missing, malformed, expired, or has the wrong type."""


def verify_auth_password(password: str) -> bool:
    """Verify the shared MVP login password from settings."""
    settings = get_settings()
    return secrets.compare_digest(password, settings.auth_password)


def verify_bot_service_token(token: str) -> bool:
    """Verify the shared bot→API service token from settings.

    Returns False when the configured token is empty (bot auth disabled)
    or when the provided token does not match.
    """
    settings = get_settings()
    expected = settings.bot_service_token
    if not expected or not token:
        return False
    return secrets.compare_digest(token, expected)


def create_access_token(
    *,
    subject: UUID,
    role: str,
    company_id: UUID,
) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return _encode_token(
        {
            "sub": str(subject),
            "role": role,
            "company_id": str(company_id),
            "type": "access",
            "exp": expire,
            "iat": datetime.now(UTC),
        }
    )


def create_refresh_token(
    *,
    subject: UUID,
    role: str,
    company_id: UUID,
) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    return _encode_token(
        {
            "sub": str(subject),
            "role": role,
            "company_id": str(company_id),
            "type": "refresh",
            "exp": expire,
            "iat": datetime.now(UTC),
        }
    )


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Invalid or expired token") from exc

    token_type = payload.get("type")
    if token_type != expected_type:
        raise InvalidTokenError(f"Invalid token type: expected {expected_type}")

    if "sub" not in payload or "role" not in payload:
        raise InvalidTokenError("Invalid token payload")

    return payload


def _encode_token(payload: dict[str, Any]) -> str:
    settings = get_settings()
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
