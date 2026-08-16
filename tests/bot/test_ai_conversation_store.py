"""Redis conversation pointer: TTL, UUID validation, no in-process fallback."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.bot.services.ai_conversation import (
    MemoryRedisClient,
    TelegramConversationStore,
)
from app.core.ai_constants import DEFAULT_TELEGRAM_CONVERSATION_TTL_SECONDS
from app.core.exceptions import ServiceUnavailableError


@pytest.mark.asyncio
async def test_get_set_clear_roundtrip() -> None:
    store = TelegramConversationStore(redis_client=MemoryRedisClient(), ttl_seconds=120)
    telegram_user_id = 42
    conversation_id = uuid4()
    assert await store.get_current_conversation(telegram_user_id) is None
    await store.set_current_conversation(telegram_user_id, conversation_id)
    assert await store.get_current_conversation(telegram_user_id) == conversation_id
    await store.clear_current_conversation(telegram_user_id)
    assert await store.get_current_conversation(telegram_user_id) is None


@pytest.mark.asyncio
async def test_invalid_redis_value_is_cleared() -> None:
    redis = MemoryRedisClient()
    store = TelegramConversationStore(redis_client=redis, ttl_seconds=120)
    redis.values[store.conversation_key(7)] = "not-a-uuid"
    assert await store.get_current_conversation(7) is None
    assert store.conversation_key(7) not in redis.values


@pytest.mark.asyncio
async def test_keys_are_per_telegram_user() -> None:
    store = TelegramConversationStore(redis_client=MemoryRedisClient(), ttl_seconds=120)
    first = uuid4()
    second = uuid4()
    await store.set_current_conversation(1, first)
    await store.set_current_conversation(2, second)
    assert await store.get_current_conversation(1) == first
    assert await store.get_current_conversation(2) == second
    assert store.conversation_key(1).startswith("bot:ai:conversation:")


def test_default_ttl_matches_constant() -> None:
    assert DEFAULT_TELEGRAM_CONVERSATION_TTL_SECONDS == 86_400


@pytest.mark.asyncio
async def test_production_redis_connect_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import Settings

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
        onboard_owner_password="unit-test-postgres-password",
        onboard_app_password="unit-test-postgres-password",
        invite_base_url="https://onboardai.example.test",
    )
    monkeypatch.setattr(
        "app.bot.services.ai_conversation.get_settings", lambda: settings
    )

    async def _boom(_url: str):
        raise ConnectionError("redis down")

    monkeypatch.setattr(
        "app.bot.services.ai_conversation._connect_redis", _boom
    )
    store = TelegramConversationStore()
    with pytest.raises(ServiceUnavailableError, match="temporarily unavailable"):
        await store.get_current_conversation(1)
