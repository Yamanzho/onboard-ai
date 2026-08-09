"""Production Redis fail-fast for bot FSM storage (P1-REDIS)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.factory import _create_storage
from app.core.config import Settings


def test_bot_storage_uses_redis_url_with_password() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        redis_url="redis://:fsm-password@redis:6379/0",
    )
    fake_storage = MagicMock(name="RedisStorage")
    with patch("aiogram.fsm.storage.redis.RedisStorage") as storage_cls:
        storage_cls.from_url.return_value = fake_storage
        result = _create_storage(settings)
    storage_cls.from_url.assert_called_once_with("redis://:fsm-password@redis:6379/0")
    assert result is fake_storage


def test_development_falls_back_to_memory_when_redis_unavailable() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        redis_url="redis://:dev-password@redis:6379/0",
    )
    with patch("aiogram.fsm.storage.redis.RedisStorage") as storage_cls:
        storage_cls.from_url.side_effect = ConnectionError("redis down")
        result = _create_storage(settings)
    assert isinstance(result, MemoryStorage)


def test_production_does_not_fall_back_to_memory_when_redis_unavailable() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        debug=False,
        secret_key="a" * 32 + "-unit-test-secret-key",
        super_admin_password="unit-test-super-admin-ok",
        redis_url="redis://:unit-test-redis-password@redis:6379/0",
        database_url=(
            "postgresql+asyncpg://onboard_app:unit-test-postgres-password@db:5432/onboard_ai"
        ),
        migration_database_url=(
            "postgresql+asyncpg://onboard_owner:unit-test-postgres-password@db:5432/onboard_ai"
        ),
    )
    with patch("aiogram.fsm.storage.redis.RedisStorage") as storage_cls:
        storage_cls.from_url.side_effect = ConnectionError("redis down")
        with pytest.raises(RuntimeError, match="Redis FSM storage is required"):
            _create_storage(settings)


def test_production_redis_auth_failure_fails_startup_storage() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        debug=False,
        secret_key="a" * 32 + "-unit-test-secret-key",
        super_admin_password="unit-test-super-admin-ok",
        redis_url="redis://:unit-test-redis-password@redis:6379/0",
        database_url=(
            "postgresql+asyncpg://onboard_app:unit-test-postgres-password@db:5432/onboard_ai"
        ),
        migration_database_url=(
            "postgresql+asyncpg://onboard_owner:unit-test-postgres-password@db:5432/onboard_ai"
        ),
    )
    with patch("aiogram.fsm.storage.redis.RedisStorage") as storage_cls:
        storage_cls.from_url.side_effect = Exception("NOAUTH Authentication required")
        with pytest.raises(RuntimeError, match="Redis FSM storage is required") as exc_info:
            _create_storage(settings)
    message = str(exc_info.value)
    assert "unit-test-redis-password" not in message
    assert "NOAUTH" not in message


def test_production_storage_error_message_does_not_leak_password() -> None:
    secret = "super-secret-redis-password-xyz"
    settings = Settings(
        _env_file=None,
        app_env="production",
        debug=False,
        secret_key="a" * 32 + "-unit-test-secret-key",
        super_admin_password="unit-test-super-admin-ok",
        redis_url=f"redis://:{secret}@redis:6379/0",
        database_url=(
            "postgresql+asyncpg://onboard_app:unit-test-postgres-password@db:5432/onboard_ai"
        ),
        migration_database_url=(
            "postgresql+asyncpg://onboard_owner:unit-test-postgres-password@db:5432/onboard_ai"
        ),
    )
    with patch("aiogram.fsm.storage.redis.RedisStorage") as storage_cls:
        storage_cls.from_url.side_effect = Exception(f"Error connecting to redis://:{secret}@redis")
        with pytest.raises(RuntimeError) as exc_info:
            _create_storage(settings)
    assert secret not in str(exc_info.value)
    assert secret not in repr(exc_info.value)
