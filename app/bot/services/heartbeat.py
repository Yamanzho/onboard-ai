"""Best-effort Telegram bot heartbeat stored in Redis."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.metrics import BOT_HEARTBEAT_KEY, BOT_HEARTBEAT_TTL_SECONDS

logger = logging.getLogger("app.bot.heartbeat")
HEARTBEAT_INTERVAL_SECONDS = 30


async def run_bot_heartbeat(stop_event: asyncio.Event) -> None:
    """Refresh a fixed, expiring key; Redis failure must not stop Telegram work."""
    client = Redis.from_url(
        get_settings().redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        decode_responses=True,
    )
    try:
        while not stop_event.is_set():
            try:
                await client.set(
                    BOT_HEARTBEAT_KEY,
                    str(datetime.now(UTC).timestamp()),
                    ex=BOT_HEARTBEAT_TTL_SECONDS,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("event=bot_heartbeat status=redis_error")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=HEARTBEAT_INTERVAL_SECONDS,
                )
            except TimeoutError:
                continue
    finally:
        await client.aclose()
