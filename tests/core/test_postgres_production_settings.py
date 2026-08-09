"""Production DATABASE_URL / Postgres password requirements (SEC-R2 + SEC-R3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import (
    Settings,
    _WEAK_POSTGRES_PASSWORDS,
    _database_url_password,
    _database_url_username,
    _MIN_POSTGRES_PASSWORD_LEN,
)

# Deterministic unit-test values — not production credentials.
_STRONG_SECRET = "unit-test-hmac-secret-key-32chars-min!!"
_STRONG_SUPER_ADMIN = "unit-test-super-admin-ok"
_STRONG_REDIS_URL = "redis://:unit-test-redis-password@redis:6379/0"
_STRONG_DB_PASSWORD = "unit-test-postgres-password"
_STRONG_DATABASE_URL = (
    f"postgresql+asyncpg://onboard_app:{_STRONG_DB_PASSWORD}@db:5432/onboard_ai"
)
_STRONG_MIGRATION_URL = (
    f"postgresql+asyncpg://onboard_owner:{_STRONG_DB_PASSWORD}@db:5432/onboard_ai"
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
        "migration_database_url": _STRONG_MIGRATION_URL,
        "onboard_owner_password": _STRONG_DB_PASSWORD,
        "onboard_app_password": _STRONG_DB_PASSWORD,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+asyncpg://onboard:onboard@localhost:5432/onboard_ai", "onboard"),
        ("postgresql+asyncpg://onboard@localhost:5432/onboard_ai", None),
        ("postgresql://u:s%40cret@db:5432/app", "s@cret"),
        ("postgresql+asyncpg://onboard:strong-enough-pw@db:5432/onboard_ai", "strong-enough-pw"),
        ("redis://:secret@redis:6379/0", None),
        ("http://example.com", None),
    ],
)
def test_database_url_password(url: str, expected: str | None) -> None:
    assert _database_url_password(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql+asyncpg://onboard_app:pw@db:5432/onboard_ai", "onboard_app"),
        ("postgresql+asyncpg://onboard_owner:pw@db:5432/onboard_ai", "onboard_owner"),
        ("postgresql+asyncpg://evil_onboard_app:pw@db:5432/onboard_ai", "evil_onboard_app"),
        ("postgresql+asyncpg://onboard_app_evil:pw@db:5432/onboard_ai", "onboard_app_evil"),
        (
            "postgresql+asyncpg://evil_onboard_app_evil:pw@db:5432/onboard_ai",
            "evil_onboard_app_evil",
        ),
        # URL-encoded underscore → decoded exact username.
        ("postgresql+asyncpg://onboard%5Fapp:pw@db:5432/onboard_ai", "onboard_app"),
        ("postgresql+asyncpg://evil%5Fonboard_app:pw@db:5432/onboard_ai", "evil_onboard_app"),
        ("postgresql+asyncpg://:pw@db:5432/onboard_ai", None),
        ("postgresql+asyncpg://db:5432/onboard_ai", None),
        ("redis://onboard_app:pw@redis:6379/0", None),
        ("http://onboard_app@example.com", None),
        ("not-a-url", None),
    ],
)
def test_database_url_username(url: str, expected: str | None) -> None:
    assert _database_url_username(url) == expected


def test_production_rejects_default_onboard_password() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL password is missing or too weak"):
        _production_settings(
            database_url="postgresql+asyncpg://onboard_app:onboard@db:5432/onboard_ai",
        )


def test_production_rejects_missing_password() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL password is missing or too weak"):
        _production_settings(
            database_url="postgresql+asyncpg://onboard_app@db:5432/onboard_ai",
        )


def test_production_rejects_empty_password() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL password is missing or too weak"):
        _production_settings(
            database_url="postgresql+asyncpg://onboard_app:@db:5432/onboard_ai",
        )


def test_production_rejects_short_password() -> None:
    short = "a" * (_MIN_POSTGRES_PASSWORD_LEN - 1)
    with pytest.raises(ValidationError, match="DATABASE_URL password is missing or too weak"):
        _production_settings(
            database_url=f"postgresql+asyncpg://onboard_app:{short}@db:5432/onboard_ai",
        )


@pytest.mark.parametrize("weak", sorted(_WEAK_POSTGRES_PASSWORDS))
def test_production_rejects_known_weak_postgres_passwords(weak: str) -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL password is missing or too weak"):
        _production_settings(
            database_url=f"postgresql+asyncpg://onboard_app:{weak}@db:5432/onboard_ai",
        )


def test_production_accepts_strong_database_password() -> None:
    settings = _production_settings(database_url=_STRONG_DATABASE_URL)
    assert settings.is_production
    assert _database_url_password(settings.database_url) == _STRONG_DB_PASSWORD


def test_production_requires_onboard_app_runtime_role() -> None:
    with pytest.raises(ValidationError, match="onboard_app"):
        _production_settings(
            database_url=f"postgresql+asyncpg://onboard:{_STRONG_DB_PASSWORD}@db:5432/onboard_ai",
        )


def test_production_requires_migration_owner_role() -> None:
    with pytest.raises(ValidationError, match="onboard_owner"):
        _production_settings(
            migration_database_url=(
                f"postgresql+asyncpg://onboard:{_STRONG_DB_PASSWORD}@db:5432/onboard_ai"
            ),
        )


@pytest.mark.parametrize(
    "username",
    [
        "evil_onboard_app",
        "onboard_app_evil",
        "evil_onboard_app_evil",
        "onboard_owner",  # owner must not be runtime
    ],
)
def test_f02_production_rejects_non_exact_runtime_usernames(username: str) -> None:
    """F-02: role check is exact parsed username — not substring."""
    with pytest.raises(ValidationError, match="onboard_app"):
        _production_settings(
            database_url=(
                f"postgresql+asyncpg://{username}:{_STRONG_DB_PASSWORD}@db:5432/onboard_ai"
            ),
        )


def test_f02_production_rejects_substring_bypass_in_password() -> None:
    """Former bypass: owner user + 'onboard_app' substring elsewhere in URL."""
    with pytest.raises(ValidationError, match="onboard_app"):
        _production_settings(
            database_url=(
                f"postgresql+asyncpg://onboard_owner:onboard_app_{_STRONG_DB_PASSWORD}"
                f"@db:5432/onboard_ai"
            ),
        )


def test_f02_production_rejects_substring_bypass_in_query() -> None:
    with pytest.raises(ValidationError, match="onboard_app"):
        _production_settings(
            database_url=(
                f"postgresql+asyncpg://onboard_owner:{_STRONG_DB_PASSWORD}"
                f"@db:5432/onboard_ai?app=onboard_app"
            ),
        )


def test_f02_production_rejects_missing_username() -> None:
    with pytest.raises(ValidationError, match="onboard_app"):
        _production_settings(
            database_url=f"postgresql+asyncpg://:{_STRONG_DB_PASSWORD}@db:5432/onboard_ai",
        )


def test_f02_production_rejects_non_postgres_scheme_with_app_in_path() -> None:
    with pytest.raises(ValidationError):
        _production_settings(
            database_url=f"redis://onboard_app:{_STRONG_DB_PASSWORD}@db:6379/0",
        )


def test_f02_production_accepts_url_encoded_exact_username() -> None:
    settings = _production_settings(
        database_url=(
            f"postgresql+asyncpg://onboard%5Fapp:{_STRONG_DB_PASSWORD}@db:5432/onboard_ai"
        ),
    )
    assert _database_url_username(settings.database_url) == "onboard_app"


def test_f02_production_rejects_url_encoded_evil_username() -> None:
    with pytest.raises(ValidationError, match="onboard_app"):
        _production_settings(
            database_url=(
                f"postgresql+asyncpg://evil%5Fonboard_app:{_STRONG_DB_PASSWORD}"
                f"@db:5432/onboard_ai"
            ),
        )


def test_f02_production_rejects_wrong_migration_role() -> None:
    with pytest.raises(ValidationError, match="onboard_owner"):
        _production_settings(
            migration_database_url=(
                f"postgresql+asyncpg://onboard_app:{_STRONG_DB_PASSWORD}@db:5432/onboard_ai"
            ),
        )


def test_production_error_does_not_echo_password() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _production_settings(
            database_url="postgresql+asyncpg://onboard_app:onboard@db:5432/onboard_ai",
        )
    err = str(exc_info.value)
    assert "DATABASE_URL password is missing or too weak" in err
    assert "onboard:onboard" not in err


def test_development_allows_default_postgres_password() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="postgresql+asyncpg://onboard_app:onboard@localhost:5432/onboard_ai",
        migration_database_url=(
            "postgresql+asyncpg://onboard_owner:unit-test-postgres-password@localhost:5432/onboard_ai"
        ),
    )
    assert not settings.is_production
    assert _database_url_password(settings.database_url) == "onboard"
