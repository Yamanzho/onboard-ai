"""Production Redis URL / password requirements (P0-03)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings, _redis_url_has_password


def _production_settings(**overrides: object) -> Settings:
    """Build Settings without reading the project ``.env`` file."""
    base: dict[str, object] = {
        "_env_file": None,
        "app_env": "production",
        "debug": False,
        "secret_key": "unit-test-hmac-secret-key-32chars-min!!",
        "super_admin_password": "unit-test-super-admin-ok",
        "redis_url": "redis://:unit-test-redis-password@redis:6379/0",
        "database_url": (
            "postgresql+asyncpg://onboard_app:unit-test-postgres-password@db:5432/onboard_ai"
        ),
        "migration_database_url": (
            "postgresql+asyncpg://onboard_owner:unit-test-postgres-password@db:5432/onboard_ai"
        ),
        "onboard_owner_password": "unit-test-postgres-password",
        "onboard_app_password": "unit-test-postgres-password",
        "invite_base_url": "https://onboardai.example.test",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("redis://localhost:6379/0", False),
        ("redis://redis:6379/0", False),
        ("redis://:@redis:6379/0", False),
        ("redis://:secret@redis:6379/0", True),
        ("redis://user:secret@redis:6379/0", True),
        ("rediss://:secret@redis:6379/0", True),
        ("http://example.com", False),
    ],
)
def test_redis_url_has_password(url: str, expected: bool) -> None:
    assert _redis_url_has_password(url) is expected


def test_production_rejects_redis_url_without_password() -> None:
    with pytest.raises(ValidationError, match="REDIS_URL must include a strong non-empty password"):
        _production_settings(redis_url="redis://redis:6379/0")


def test_production_rejects_empty_redis_password() -> None:
    with pytest.raises(ValidationError, match="REDIS_URL must include a strong non-empty password"):
        _production_settings(redis_url="redis://:@redis:6379/0")


def test_production_accepts_redis_url_with_password() -> None:
    settings = _production_settings(
        redis_url="redis://:unit-test-redis-password@redis:6379/0",
    )
    assert settings.is_production
    assert _redis_url_has_password(settings.redis_url)


def test_development_allows_redis_without_password() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        redis_url="redis://localhost:6379/0",
    )
    assert not settings.is_production
    assert settings.redis_url == "redis://localhost:6379/0"
