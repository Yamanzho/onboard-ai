"""Production rate limiter must not silently fall back to process-local memory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import Settings, get_settings
from app.core.exceptions import ServiceUnavailableError
from app.core.rate_limit import is_rate_limited, reset_rate_limiter_state_for_tests


@pytest.fixture(autouse=True)
def _reset_limiter(monkeypatch: pytest.MonkeyPatch):
    reset_rate_limiter_state_for_tests()
    get_settings.cache_clear()
    yield
    reset_rate_limiter_state_for_tests()
    get_settings.cache_clear()


def _production_settings(**overrides: object) -> Settings:
    values = {
        "app_env": "production",
        "debug": False,
        "secret_key": "a" * 32 + "-unit-test-secret-key",
        "super_admin_password": "unit-test-super-admin-ok",
        "redis_url": "redis://:unit-test-redis-password@redis:6379/0",
        "database_url": (
            "postgresql+asyncpg://onboard_app:unit-test-postgres-password@db:5432/onboard_ai"
        ),
        "migration_database_url": (
            "postgresql+asyncpg://onboard_owner:unit-test-postgres-password@db:5432/onboard_ai"
        ),
        **overrides,
    }
    return Settings(_env_file=None, **values)


def test_production_redis_unavailable_does_not_use_memory_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _production_settings()
    monkeypatch.setattr("app.core.rate_limit.get_settings", lambda: settings)

    with patch("redis.Redis") as redis_cls:
        client = MagicMock()
        client.ping.side_effect = ConnectionError("redis down")
        redis_cls.from_url.return_value = client
        with pytest.raises(ServiceUnavailableError, match="Rate limiting temporarily unavailable"):
            is_rate_limited("prod:login:ip:1.2.3.4", limit=10, window_seconds=60)


def test_production_redis_command_failure_does_not_use_memory_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _production_settings()
    monkeypatch.setattr("app.core.rate_limit.get_settings", lambda: settings)

    client = MagicMock()
    client.ping.return_value = True
    client.incr.side_effect = ConnectionError("broken pipe")

    with patch("redis.Redis") as redis_cls:
        redis_cls.from_url.return_value = client
        with pytest.raises(ServiceUnavailableError, match="Rate limiting temporarily unavailable"):
            is_rate_limited("prod:login:ip:9.9.9.9", limit=10, window_seconds=60)


def test_production_memory_fallback_not_used_across_workers_conceptually(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove production path never reaches process-local memory counters.

    Two logical "workers" share the production code path; when Redis is down,
    both raise instead of accumulating independent in-memory hits that would
    dilute the shared limit.
    """
    settings = _production_settings()
    monkeypatch.setattr("app.core.rate_limit.get_settings", lambda: settings)

    with patch("redis.Redis") as redis_cls:
        client = MagicMock()
        client.ping.side_effect = ConnectionError("redis down")
        redis_cls.from_url.return_value = client

        for worker_key in ("worker-a", "worker-b"):
            reset_rate_limiter_state_for_tests()
            with pytest.raises(ServiceUnavailableError):
                is_rate_limited(
                    f"{worker_key}:login:ip:1.1.1.1",
                    limit=1,
                    window_seconds=60,
                )


def test_development_still_falls_back_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        redis_url="redis://localhost:6379/0",
    )
    monkeypatch.setattr("app.core.rate_limit.get_settings", lambda: settings)

    with patch("redis.Redis") as redis_cls:
        client = MagicMock()
        client.ping.side_effect = ConnectionError("redis down")
        redis_cls.from_url.return_value = client

        # First call marks Redis failed and uses memory; should not raise.
        assert (
            is_rate_limited("dev:login:ip:1.2.3.4", limit=2, window_seconds=60) is False
        )
        assert (
            is_rate_limited("dev:login:ip:1.2.3.4", limit=2, window_seconds=60) is False
        )
        assert (
            is_rate_limited("dev:login:ip:1.2.3.4", limit=2, window_seconds=60) is True
        )


def test_production_error_does_not_leak_redis_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "super-secret-redis-password-xyz"
    settings = _production_settings(redis_url=f"redis://:{secret}@redis:6379/0")
    monkeypatch.setattr("app.core.rate_limit.get_settings", lambda: settings)

    with patch("redis.Redis") as redis_cls:
        client = MagicMock()
        client.ping.side_effect = Exception(f"Error for redis://:{secret}@redis")
        redis_cls.from_url.return_value = client
        with pytest.raises(ServiceUnavailableError) as exc_info:
            is_rate_limited("prod:login:ip:1.2.3.4", limit=10, window_seconds=60)
    assert secret not in exc_info.value.message
    assert secret not in str(exc_info.value)
