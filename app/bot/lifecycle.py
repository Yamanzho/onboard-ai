"""Shared Telegram bot shutdown helpers. Do not change delivery semantics."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable
from typing import Any

from aiohttp import web

from app.bot.services.ai_conversation import get_telegram_conversation_store
from app.core.config import get_settings

logger = logging.getLogger("app.bot.lifecycle")


def health_response(_request: web.Request) -> web.Response:
    """Shallow process liveness. Does not call Telegram or the public API."""
    return web.json_response({"status": "ok"})


async def await_background_task(task: asyncio.Task[Any] | None, *, timeout: float) -> None:
    if task is None:
        return
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
    except TimeoutError:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            logger.warning("event=shutdown component=background_task result=timeout")
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("event=shutdown component=background_task result=close_error")


async def close_dispatcher_storage(dispatcher: object) -> None:
    storage = getattr(dispatcher, "storage", None)
    close = getattr(storage, "close", None)
    if close is None:
        return
    try:
        result = close()
        if isinstance(result, Awaitable):
            await asyncio.wait_for(result, timeout=2)
    except Exception:
        logger.warning("event=shutdown component=fsm_storage result=close_error")


async def close_conversation_store() -> None:
    try:
        await asyncio.wait_for(get_telegram_conversation_store().aclose(), timeout=2)
    except Exception:
        logger.warning("event=shutdown component=conversation_store result=close_error")


async def shutdown_bot_runtime(
    *,
    outbound_stop: asyncio.Event | None,
    heartbeat_stop: asyncio.Event | None,
    outbound_task: asyncio.Task[Any] | None,
    heartbeat_task: asyncio.Task[Any] | None,
    dispatcher: object | None,
    api_client: object,
    bot: object,
    delete_webhook: bool,
    reminder_stop: asyncio.Event | None = None,
    reminder_task: asyncio.Task[Any] | None = None,
) -> None:
    """Stop loops, then close clients. Redis/Telegram close failures do not hang."""
    if outbound_stop is not None:
        outbound_stop.set()
    if heartbeat_stop is not None:
        heartbeat_stop.set()
    if reminder_stop is not None:
        reminder_stop.set()
    timeout = max(5.0, get_settings().shutdown_grace_seconds - 5.0)
    await await_background_task(outbound_task, timeout=timeout)
    await await_background_task(heartbeat_task, timeout=5.0)
    await await_background_task(reminder_task, timeout=5.0)
    if dispatcher is not None:
        await close_dispatcher_storage(dispatcher)
    await close_conversation_store()
    if delete_webhook:
        try:
            await bot.delete_webhook(drop_pending_updates=False)  # type: ignore[attr-defined]
        except Exception:
            logger.warning("event=shutdown component=telegram_webhook result=close_error")
    try:
        await asyncio.wait_for(api_client.aclose(), timeout=2)  # type: ignore[attr-defined]
    except Exception:
        logger.warning("event=shutdown component=api_client result=close_error")
    try:
        await asyncio.wait_for(bot.session.close(), timeout=2)  # type: ignore[attr-defined]
    except Exception:
        logger.warning("event=shutdown component=telegram_session result=close_error")
