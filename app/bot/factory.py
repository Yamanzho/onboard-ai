"""aiogram Bot / Dispatcher factory (webhook-ready)."""

from __future__ import annotations

import logging
from uuid import UUID

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.api.client import OnboardApiClient
from app.bot.handlers import get_handlers_router
from app.bot.middlewares.api_client import ApiClientMiddleware
from app.bot.middlewares.idempotency import TelegramUpdateIdempotencyMiddleware
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


def create_api_client(settings: Settings | None = None) -> OnboardApiClient:
    settings = settings or get_settings()
    if not settings.bot_service_token:
        raise RuntimeError("BOT_SERVICE_TOKEN is required for the Telegram bot")
    company_id: UUID | None = None
    if settings.bot_company_id.strip():
        company_id = UUID(settings.bot_company_id)
    return OnboardApiClient(
        base_url=settings.api_base_url,
        company_id=company_id,
        service_token=settings.bot_service_token,
    )


def create_bot(settings: Settings | None = None) -> Bot:
    settings = settings or get_settings()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is required for the Telegram bot")
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def _create_storage(settings: Settings) -> BaseStorage:
    """Create FSM storage.

    Production: Redis is required — initialization failure raises (no MemoryStorage).
    Development: falls back to MemoryStorage when Redis is unavailable.
    Error messages never include Redis credentials.
    """
    try:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)
    except Exception:
        if settings.is_production:
            logger.error(
                "Bot FSM: Redis storage required when APP_ENV=production but unavailable"
            )
            raise RuntimeError(
                "Redis FSM storage is required when APP_ENV=production "
                "(Redis unreachable, auth failed, or REDIS_URL misconfigured)"
            ) from None
        logger.warning(
            "Bot FSM: Redis unavailable, using MemoryStorage "
            "(development only; not shared/durable)"
        )
        return MemoryStorage()


def create_dispatcher(
    api_client: OnboardApiClient,
    settings: Settings | None = None,
) -> Dispatcher:
    settings = settings or get_settings()
    dispatcher = Dispatcher(storage=_create_storage(settings))
    dispatcher.update.middleware(TelegramUpdateIdempotencyMiddleware(api_client))
    dispatcher.update.middleware(ApiClientMiddleware(api_client))
    dispatcher.include_router(get_handlers_router())
    return dispatcher
