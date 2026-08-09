from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.exceptions import AppError

TokenType = Literal["access", "refresh"]

_PBKDF2_SCHEME = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 120_000
# Interactive Argon2id parameters (OWASP-aligned for typical API hosts).
_ARGON2 = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)


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
    """Hash a password with Argon2id (new hashes)."""
    return _ARGON2.hash(password)


def password_hash_needs_upgrade(password_hash: str | None) -> bool:
    """True when the stored hash should be replaced with current Argon2id params."""
    if not password_hash:
        return False
    if password_hash.startswith(f"{_PBKDF2_SCHEME}$"):
        return True
    if password_hash.startswith("$argon2"):
        try:
            return _ARGON2.check_needs_rehash(password_hash)
        except (InvalidHashError, VerificationError):
            return True
    return True


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against Argon2id or legacy PBKDF2-SHA256 hashes."""
    if password_hash.startswith("$argon2"):
        try:
            return _ARGON2.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError):
            return False

    try:
        scheme, iterations_s, salt, expected_hex = password_hash.split("$", 3)
    except ValueError:
        return False
    if scheme != _PBKDF2_SCHEME:
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

    Users with a personal hash must use it. Legacy/demo users without a hash
    may use the shared ``AUTH_PASSWORD`` only when
    ``allow_shared_auth_password`` is enabled (never in production).
    """
    if password_hash:
        return verify_password(password, password_hash)
    settings = get_settings()
    if not settings.allow_shared_auth_password:
        return False
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
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
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
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
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
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={
                "require": ["exp", "iat", "sub", "role", "type", "iss", "aud"],
            },
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
