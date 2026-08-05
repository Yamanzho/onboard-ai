from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt

from app.core.config import get_settings
from app.core.exceptions import AppError

TokenType = Literal["access", "refresh"]

_PBKDF2_ITERATIONS = 120_000


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


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-SHA256 (stdlib; no extra deps)."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        _PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a hash produced by ``hash_password``."""
    try:
        scheme, iterations_s, salt, expected_hex = password_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != "pbkdf2_sha256":
        return False
    try:
        iterations = int(iterations_s)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(digest.hex(), expected_hex)


def hash_token(token: str) -> str:
    """Hash an opaque token (invite links) with SHA-256."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_employee_password(*, password: str, password_hash: str | None) -> bool:
    """Verify employee login password.

    Invited users with a personal hash must use it. Legacy/demo users without
    a hash continue to use the shared ``AUTH_PASSWORD``.
    """
    if password_hash:
        return verify_password(password, password_hash)
    return verify_auth_password(password)


def create_access_token(
    *,
    subject: UUID,
    role: str,
    company_id: UUID | None = None,
) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    return _encode_token(
        {
            "sub": str(subject),
            "role": role,
            "company_id": str(company_id) if company_id is not None else None,
            "type": "access",
            "exp": expire,
            "iat": datetime.now(UTC),
        }
    )


def create_refresh_token(
    *,
    subject: UUID,
    role: str,
    company_id: UUID | None = None,
) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    return _encode_token(
        {
            "sub": str(subject),
            "role": role,
            "company_id": str(company_id) if company_id is not None else None,
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
