"""aiogram Bot / Dispatcher factory (webhook-ready)."""

from __future__ import annotations

from uuid import UUID

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.api.client import OnboardApiClient
from app.bot.handlers import get_handlers_router
from app.bot.middlewares.api_client import ApiClientMiddleware
from app.core.config import Settings, get_settings


def create_api_client(settings: Settings | None = None) -> OnboardApiClient:
    settings = settings or get_settings()
    if not settings.bot_company_id:
        raise RuntimeError("BOT_COMPANY_ID is required for the Telegram bot")
    if not settings.bot_service_token:
        raise RuntimeError("BOT_SERVICE_TOKEN is required for the Telegram bot")
    return OnboardApiClient(
        base_url=settings.api_base_url,
        company_id=UUID(settings.bot_company_id),
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
    try:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(settings.redis_url)
    except Exception:
        return MemoryStorage()


def create_dispatcher(
    api_client: OnboardApiClient,
    settings: Settings | None = None,
) -> Dispatcher:
    settings = settings or get_settings()
    dispatcher = Dispatcher(storage=_create_storage(settings))
    dispatcher.update.middleware(ApiClientMiddleware(api_client))
    dispatcher.include_router(get_handlers_router())
    return dispatcher
