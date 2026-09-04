"""Periodic assignment reminder scan. Enqueue is DB-idempotent."""

from __future__ import annotations

import asyncio
import logging

from app.bot.api.client import OnboardApiClient

logger = logging.getLogger("app.bot.reminders")

REMINDER_SCAN_INTERVAL_SECONDS = 60.0


async def run_reminder_scan(
    api_client: OnboardApiClient,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            result = await api_client.scan_assignment_reminders()
            logger.info(
                "assignment_reminder_scan scanned=%s enqueued=%s",
                result.get("scanned", 0),
                result.get("enqueued", 0),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("assignment_reminder_scan status=error")
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=REMINDER_SCAN_INTERVAL_SECONDS,
            )
        except TimeoutError:
            continue
