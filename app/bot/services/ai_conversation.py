"""Ephemeral Telegram → conversation_id pointer. Not authorization.

PostgreSQL (`AIConversation` / `AIMessage`) is the source of truth.
Redis only remembers which conversation is currently open for a Telegram user.
HTTP chat remains the authorization boundary.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from app.core.ai_constants import DEFAULT_TELEGRAM_CONVERSATION_TTL_SECONDS
from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError

logger = logging.getLogger("app.bot.ai.conversation")

_KEY_PREFIX = "bot:ai:conversation:"
_PROD_REDIS_UNAVAILABLE = "Conversation session temporarily unavailable"


class AsyncRedisClient(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def set(self, key: str, value: str, ex: int | None = None) -> Any: ...

    async def delete(self, key: str) -> Any: ...


class MemoryRedisClient:
    """In-process Redis stand-in for tests. Never used as a production fallback."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.values[key] = value
        return True

    async def delete(self, key: str) -> int:
        return 1 if self.values.pop(key, None) is not None else 0


class TelegramConversationStore:
    """Maps Telegram user id → current conversation UUID. Not an ACL layer."""

    def __init__(
        self,
        *,
        redis_client: AsyncRedisClient | None = None,
        redis_factory: Callable[[], AsyncRedisClient] | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self._injected = redis_client
        self._redis_factory = redis_factory
        self._client: AsyncRedisClient | None = redis_client
        self._ttl_seconds = ttl_seconds
        self._dev_unavailable = False

    def conversation_key(self, telegram_user_id: int) -> str:
        return f"{_KEY_PREFIX}{telegram_user_id}"

    def _ttl(self) -> int:
        if self._ttl_seconds is not None:
            return self._ttl_seconds
        return get_settings().ai_telegram_conversation_ttl_seconds

    async def get_current_conversation(self, telegram_user_id: int) -> UUID | None:
        raw = await self._get(self.conversation_key(telegram_user_id))
        if raw is None or not str(raw).strip():
            return None
        try:
            return UUID(str(raw).strip())
        except ValueError:
            await self.clear_current_conversation(telegram_user_id)
            return None

    async def set_current_conversation(
        self,
        telegram_user_id: int,
        conversation_id: UUID,
    ) -> None:
        await self._set(
            self.conversation_key(telegram_user_id),
            str(conversation_id),
            ex=self._ttl(),
        )

    async def clear_current_conversation(self, telegram_user_id: int) -> None:
        await self._delete(self.conversation_key(telegram_user_id))

    async def _get(self, key: str) -> str | None:
        client = await self._client_or_none()
        if client is None:
            return None
        try:
            value = await client.get(key)
        except Exception:
            self._on_command_error()
            return None
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def _set(self, key: str, value: str, *, ex: int) -> None:
        client = await self._client_or_none()
        if client is None:
            return
        try:
            await client.set(key, value, ex=ex)
        except Exception:
            self._on_command_error()

    async def _delete(self, key: str) -> None:
        client = await self._client_or_none()
        if client is None:
            return
        try:
            await client.delete(key)
        except Exception:
            self._on_command_error()

    async def _client_or_none(self) -> AsyncRedisClient | None:
        if self._injected is not None:
            return self._injected
        if self._client is not None:
            return self._client
        if self._dev_unavailable:
            return None
        settings = get_settings()
        try:
            if self._redis_factory is not None:
                self._client = self._redis_factory()
            else:
                self._client = await _connect_redis(settings.redis_url)
            return self._client
        except Exception:
            if settings.is_production:
                logger.error(
                    "Telegram conversation pointer: Redis required when "
                    "APP_ENV=production but unavailable"
                )
                raise ServiceUnavailableError(_PROD_REDIS_UNAVAILABLE) from None
            logger.warning(
                "Telegram conversation pointer: Redis unavailable; "
                "next messages start a new conversation (development only)"
            )
            self._dev_unavailable = True
            return None

    def _on_command_error(self) -> None:
        if get_settings().is_production:
            logger.error(
                "Telegram conversation pointer: Redis command failed in production; "
                "refusing in-process fallback"
            )
            raise ServiceUnavailableError(_PROD_REDIS_UNAVAILABLE) from None
        logger.warning(
            "Telegram conversation pointer: Redis command failed; "
            "treating pointer as missing (development only)"
        )
        self._dev_unavailable = True
        self._client = None


_store: TelegramConversationStore | None = None


def get_telegram_conversation_store() -> TelegramConversationStore:
    global _store
    if _store is None:
        _store = TelegramConversationStore()
    return _store


def reset_telegram_conversation_store_for_tests() -> None:
    global _store
    _store = None


async def _connect_redis(redis_url: str) -> AsyncRedisClient:
    from redis.asyncio import Redis

    client = Redis.from_url(redis_url, decode_responses=True)
    await client.ping()
    return client


def default_ttl_seconds() -> int:
    return DEFAULT_TELEGRAM_CONVERSATION_TTL_SECONDS
