"""Telegram bot entrypoint.

Run with: python -m app.bot

Modes:
- polling (default for local): when ``BOT_WEBHOOK_URL`` is empty
- webhook: when ``BOT_WEBHOOK_URL`` is set (aiohttp server on BOT_WEBHOOK_PORT)
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from app.bot.factory import create_api_client, create_bot, create_dispatcher
from app.bot.lifecycle import health_response, shutdown_bot_runtime
from app.bot.services.heartbeat import run_bot_heartbeat
from app.bot.services.outbound_delivery import TelegramOutboundExecutor
from app.core.config import get_settings

logger = logging.getLogger(__name__)


async def on_startup(app: web.Application) -> None:
    bot: object = app["bot"]
    settings = get_settings()
    api_client = app["api_client"]
    await api_client.start()
    outbound_stop = asyncio.Event()
    outbound_task = asyncio.create_task(
        TelegramOutboundExecutor(bot, api_client).run(outbound_stop)
    )
    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(run_bot_heartbeat(heartbeat_stop))
    app["outbound_stop"] = outbound_stop
    app["outbound_task"] = outbound_task
    app["heartbeat_stop"] = heartbeat_stop
    app["heartbeat_task"] = heartbeat_task

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
    await shutdown_bot_runtime(
        outbound_stop=app.get("outbound_stop"),
        heartbeat_stop=app.get("heartbeat_stop"),
        outbound_task=app.get("outbound_task"),
        heartbeat_task=app.get("heartbeat_task"),
        dispatcher=app.get("dispatcher"),
        api_client=app["api_client"],
        bot=app["bot"],
        delete_webhook=bool(get_settings().bot_webhook_url),
    )


def create_webhook_app() -> web.Application:
    settings = get_settings()
    api_client = create_api_client(settings)
    bot = create_bot(settings)
    dispatcher = create_dispatcher(api_client, settings)

    app = web.Application()
    app["bot"] = bot
    app["dispatcher"] = dispatcher
    app["api_client"] = api_client
    app.router.add_get("/health", health_response)

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
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame: stop.set())

    await api_client.start()
    outbound_stop = asyncio.Event()
    outbound_task = asyncio.create_task(
        TelegramOutboundExecutor(bot, api_client).run(outbound_stop)
    )
    heartbeat_stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(run_bot_heartbeat(heartbeat_stop))
    health_app = web.Application()
    health_app.router.add_get("/health", health_response)
    health_runner = web.AppRunner(health_app)
    await health_runner.setup()
    health_site = web.TCPSite(health_runner, host="127.0.0.1", port=settings.bot_webhook_port)
    await health_site.start()
    polling_task = asyncio.create_task(
        _run_polling_until_stop(bot, dispatcher, stop)
    )
    try:
        await polling_task
    finally:
        await shutdown_bot_runtime(
            outbound_stop=outbound_stop,
            heartbeat_stop=heartbeat_stop,
            outbound_task=outbound_task,
            heartbeat_task=heartbeat_task,
            dispatcher=dispatcher,
            api_client=api_client,
            bot=bot,
            delete_webhook=False,
        )
        await health_runner.cleanup()


async def _run_polling_until_stop(bot: object, dispatcher: object, stop: asyncio.Event) -> None:
    await bot.delete_webhook(drop_pending_updates=True)  # type: ignore[attr-defined]
    logger.info("Starting bot in polling mode (BOT_WEBHOOK_URL is empty)")
    polling = asyncio.create_task(
        dispatcher.start_polling(bot, close_bot_session=False)  # type: ignore[attr-defined]
    )
    stopper = asyncio.create_task(stop.wait())
    done, _pending = await asyncio.wait(
        {polling, stopper},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if stopper in done and not polling.done():
        await dispatcher.stop_polling()  # type: ignore[attr-defined]
        await polling
    else:
        stopper.cancel()
        await polling


def run_webhook() -> None:
    settings = get_settings()
    app = create_webhook_app()
    web.run_app(
        app,
        host=settings.bot_webhook_host,
        port=settings.bot_webhook_port,
        shutdown_timeout=settings.shutdown_grace_seconds,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s level=%(levelname)s component=%(name)s %(message)s"
        ),
    )
    settings = get_settings()

    if not settings.bot_token:
        logger.error("BOT_TOKEN is required")
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
