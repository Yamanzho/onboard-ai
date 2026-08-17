"""Production secret fail-fast (P0-02): SECRET_KEY, SUPER_ADMIN_PASSWORD, Redis."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import (
    Settings,
    _is_missing_or_weak_secret,
    _WEAK_SECRET_KEYS,
    _WEAK_SUPER_ADMIN_PASSWORDS,
    _MIN_SECRET_KEY_LEN,
    _MIN_SUPER_ADMIN_PASSWORD_LEN,
)

# Deterministic unit-test values — not production credentials.
_STRONG_SECRET = "unit-test-hmac-secret-key-32chars-min!!"
_STRONG_SUPER_ADMIN = "unit-test-super-admin-ok"
_STRONG_REDIS_URL = "redis://:unit-test-redis-password@redis:6379/0"
_STRONG_DATABASE_URL = (
    "postgresql+asyncpg://onboard_app:unit-test-postgres-password@db:5432/onboard_ai"
)


def _production_settings(**overrides: object) -> Settings:
    """Build production Settings without reading the project ``.env`` file."""
    base: dict[str, object] = {
        "_env_file": None,
        "app_env": "production",
        "debug": False,
        "secret_key": _STRONG_SECRET,
        "super_admin_password": _STRONG_SUPER_ADMIN,
        "redis_url": _STRONG_REDIS_URL,
        "database_url": _STRONG_DATABASE_URL,
        "migration_database_url": "postgresql+asyncpg://onboard_owner:unit-test-postgres-password@db:5432/onboard_ai",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --- SECRET_KEY ---


def test_production_rejects_default_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY is missing or too weak"):
        _production_settings(secret_key="change-me")


def test_production_rejects_empty_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY is missing or too weak"):
        _production_settings(secret_key="")


def test_production_rejects_whitespace_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY is missing or too weak"):
        _production_settings(secret_key="   ")


def test_production_rejects_short_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY is missing or too weak"):
        _production_settings(secret_key="a" * (_MIN_SECRET_KEY_LEN - 1))


@pytest.mark.parametrize("weak", sorted(_WEAK_SECRET_KEYS))
def test_production_rejects_known_weak_secret_keys(weak: str) -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY is missing or too weak"):
        _production_settings(secret_key=weak)


def test_production_rejects_placeholder_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY is missing or too weak"):
        _production_settings(secret_key="<generate-a-strong-random-secret>")


def test_production_accepts_strong_secret_key() -> None:
    settings = _production_settings(secret_key=_STRONG_SECRET)
    assert settings.is_production
    assert settings.secret_key == _STRONG_SECRET


# --- SUPER_ADMIN_PASSWORD ---


def test_production_rejects_default_super_admin_password() -> None:
    with pytest.raises(ValidationError, match="SUPER_ADMIN_PASSWORD is missing or too weak"):
        _production_settings(super_admin_password="change-me-super-admin")


def test_production_rejects_empty_super_admin_password() -> None:
    with pytest.raises(ValidationError, match="SUPER_ADMIN_PASSWORD is missing or too weak"):
        _production_settings(super_admin_password="")


def test_production_rejects_short_super_admin_password() -> None:
    with pytest.raises(ValidationError, match="SUPER_ADMIN_PASSWORD is missing or too weak"):
        _production_settings(super_admin_password="a" * (_MIN_SUPER_ADMIN_PASSWORD_LEN - 1))


@pytest.mark.parametrize(
    "weak",
    ["admin", "admin123", "password", "password123", "<set-a-strong-unique-password>"],
)
def test_production_rejects_weak_super_admin_passwords(weak: str) -> None:
    with pytest.raises(ValidationError, match="SUPER_ADMIN_PASSWORD is missing or too weak"):
        _production_settings(super_admin_password=weak)


def test_production_accepts_strong_super_admin_password() -> None:
    settings = _production_settings(super_admin_password=_STRONG_SUPER_ADMIN)
    assert settings.super_admin_password == _STRONG_SUPER_ADMIN


def test_production_allows_shared_bot_without_company_id() -> None:
    settings = _production_settings(
        bot_service_token="unit-test-bot-service-token-32chars",
        bot_company_id="",
    )
    assert settings.bot_company_id == ""
    assert settings.bot_service_token == "unit-test-bot-service-token-32chars"


def test_production_rejects_demo_seed_bot_company_id() -> None:
    with pytest.raises(ValidationError, match="demo seed company id"):
        _production_settings(
            bot_service_token="unit-test-bot-service-token-32chars",
            bot_company_id="11111111-1111-4111-8111-111111111111",
        )


# --- REDIS (P0-03 interaction; must remain enforced) ---


def test_production_rejects_redis_without_auth() -> None:
    with pytest.raises(ValidationError, match="REDIS_URL must include a non-empty password"):
        _production_settings(redis_url="redis://redis:6379/0")


def test_production_accepts_redis_with_password() -> None:
    settings = _production_settings(redis_url=_STRONG_REDIS_URL)
    assert settings.is_production


# --- Development must stay usable ---


def test_development_allows_default_secrets() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        secret_key="change-me",
        super_admin_password="change-me-super-admin",
        redis_url="redis://localhost:6379/0",
    )
    assert not settings.is_production
    assert settings.secret_key == "change-me"
    assert settings.super_admin_password == "change-me-super-admin"


def test_error_messages_do_not_echo_secret_values() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _production_settings(secret_key="short-insecure")
    err = str(exc_info.value)
    assert "SECRET_KEY is missing or too weak" in err
    assert "short-insecure" not in err

    with pytest.raises(ValidationError) as exc_info:
        _production_settings(super_admin_password="admin123")
    err = str(exc_info.value)
    assert "SUPER_ADMIN_PASSWORD is missing or too weak" in err
    assert "admin123" not in err


def test_helper_detects_placeholder_and_weak() -> None:
    assert _is_missing_or_weak_secret(
        "",
        weak_values=_WEAK_SECRET_KEYS,
        min_length=_MIN_SECRET_KEY_LEN,
    )
    assert _is_missing_or_weak_secret(
        "<generate-a-strong-random-secret>",
        weak_values=_WEAK_SECRET_KEYS,
        min_length=_MIN_SECRET_KEY_LEN,
    )
    assert not _is_missing_or_weak_secret(
        _STRONG_SECRET,
        weak_values=_WEAK_SECRET_KEYS,
        min_length=_MIN_SECRET_KEY_LEN,
    )
    assert _is_missing_or_weak_secret(
        "change-me-super-admin",
        weak_values=_WEAK_SUPER_ADMIN_PASSWORDS,
        min_length=_MIN_SUPER_ADMIN_PASSWORD_LEN,
    )
