"""Telegram bot entrypoint.

Run with: python -m app.bot

Modes:
- polling (default for local): when ``BOT_WEBHOOK_URL`` is empty
- webhook: when ``BOT_WEBHOOK_URL`` is set (aiohttp server on BOT_WEBHOOK_PORT)
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.bot.factory import create_api_client, create_bot, create_dispatcher
from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def on_startup(app: web.Application) -> None:
    bot: object = app["bot"]
    settings = get_settings()
    api_client = app["api_client"]
    await api_client.start()

    if settings.bot_webhook_url:
        await bot.set_webhook(  # type: ignore[attr-defined]
            url=settings.bot_webhook_url,
            secret_token=settings.bot_webhook_secret or None,
            drop_pending_updates=True,
        )
        logger.info("Webhook set to %s", settings.bot_webhook_url)
    else:
        logger.warning(
            "BOT_WEBHOOK_URL is empty — webhook server is listening, "
            "but Telegram webhook is not registered"
        )


async def on_shutdown(app: web.Application) -> None:
    bot = app["bot"]
    api_client = app["api_client"]
    settings = get_settings()
    if settings.bot_webhook_url:
        await bot.delete_webhook(drop_pending_updates=False)  # type: ignore[attr-defined]
    await api_client.aclose()
    await bot.session.close()  # type: ignore[attr-defined]


def create_webhook_app() -> web.Application:
    settings = get_settings()
    api_client = create_api_client(settings)
    bot = create_bot(settings)
    dispatcher = create_dispatcher(api_client, settings)

    app = web.Application()
    app["bot"] = bot
    app["dispatcher"] = dispatcher
    app["api_client"] = api_client

    webhook_path = settings.bot_webhook_path or "/webhook"
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.bot_webhook_secret or None,
    ).register(app, path=webhook_path)
    setup_application(app, dispatcher, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


async def run_polling() -> None:
    """Long-polling mode for local development (no public HTTPS URL required)."""
    settings = get_settings()
    api_client = create_api_client(settings)
    bot = create_bot(settings)
    dispatcher = create_dispatcher(api_client, settings)

    await api_client.start()
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Starting bot in polling mode (BOT_WEBHOOK_URL is empty)")
        await dispatcher.start_polling(bot)
    finally:
        await api_client.aclose()
        await bot.session.close()


def run_webhook() -> None:
    settings = get_settings()
    app = create_webhook_app()
    web.run_app(
        app,
        host=settings.bot_webhook_host,
        port=settings.bot_webhook_port,
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()

    if not settings.bot_token:
        logger.error("BOT_TOKEN is required")
        sys.exit(1)
    if not settings.bot_company_id:
        logger.error("BOT_COMPANY_ID is required")
        sys.exit(1)
    if not settings.bot_service_token:
        logger.error("BOT_SERVICE_TOKEN is required")
        sys.exit(1)

    if settings.bot_webhook_url:
        if not settings.bot_webhook_secret:
            logger.error(
                "BOT_WEBHOOK_SECRET is required when BOT_WEBHOOK_URL is set"
            )
            sys.exit(1)
        logger.info("BOT_WEBHOOK_URL set — starting webhook server")
        run_webhook()
    else:
        asyncio.run(run_polling())


if __name__ == "__main__":
    main()
