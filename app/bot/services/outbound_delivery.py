from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramEntityTooLarge,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)

from app.bot.api.client import (
    OnboardApiClient,
    TelegramOutboundDelivery,
)

logger = logging.getLogger("app.bot.outbound")

OUTBOUND_POLL_INTERVAL_SECONDS = 5.0
OUTBOUND_WORKER_BATCH_SIZE = 20


@dataclass(frozen=True, slots=True)
class TelegramFailure:
    retryable: bool
    category: str
    retry_after_seconds: int | None = None


class TelegramOutboundExecutor:
    """One shared immediate/background path for durable Telegram sends."""

    def __init__(self, bot: Bot, api_client: OnboardApiClient) -> None:
        self._bot = bot
        self._api = api_client

    async def deliver_source(
        self,
        *,
        source_type: str,
        source_key: str,
    ) -> bool:
        """Return False only when no durable outbound exists for the source."""
        delivery = await self._api.claim_telegram_outbound(
            source_type=source_type,
            source_key=source_key,
        )
        if delivery.state == "not_found":
            return False
        if delivery.acquired:
            await self.deliver_claimed(delivery)
        return True

    async def deliver_claimed(
        self,
        delivery: TelegramOutboundDelivery,
    ) -> None:
        if (
            not delivery.acquired
            or delivery.message_id is None
            or delivery.owner_token is None
            or delivery.chat_id is None
            or delivery.body is None
        ):
            raise ValueError("A complete acquired Telegram outbound is required")

        started = time.perf_counter()
        try:
            sent = await self._bot.send_message(
                chat_id=delivery.chat_id,
                text=delivery.body,
                parse_mode=delivery.parse_mode,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = classify_telegram_failure(exc)
            await self._api.mark_telegram_outbound_failed(
                message_id=delivery.message_id,
                owner_token=delivery.owner_token,
                retryable=failure.retryable,
                error_category=failure.category,
                retry_after_seconds=failure.retry_after_seconds,
            )
            logger.warning(
                "telegram_outbound outbound_message_id=%s source_type=%s "
                "source_key=%s attempt=%s status=%s error_category=%s "
                "latency_ms=%.2f",
                delivery.message_id,
                delivery.source_type or "",
                delivery.source_key or "",
                delivery.attempt_count,
                "retry_scheduled" if failure.retryable else "failed",
                failure.category,
                (time.perf_counter() - started) * 1000,
            )
            return

        updated = await self._api.mark_telegram_outbound_sent(
            message_id=delivery.message_id,
            owner_token=delivery.owner_token,
            telegram_message_id=sent.message_id,
        )
        logger.info(
            "telegram_outbound outbound_message_id=%s source_type=%s "
            "source_key=%s attempt=%s status=%s telegram_message_id=%s "
            "latency_ms=%.2f",
            delivery.message_id,
            delivery.source_type or "",
            delivery.source_key or "",
            delivery.attempt_count,
            "sent" if updated else "ack_ownership_lost",
            sent.message_id,
            (time.perf_counter() - started) * 1000,
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        """Poll bounded batches until clean shutdown."""
        while not stop_event.is_set():
            try:
                if stop_event.is_set():
                    return
                deliveries = await self._api.claim_due_telegram_outbound(
                    limit=OUTBOUND_WORKER_BATCH_SIZE
                )
                for delivery in deliveries:
                    if stop_event.is_set():
                        break
                    await self.deliver_claimed(delivery)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("telegram_outbound_worker status=poll_error")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=OUTBOUND_POLL_INTERVAL_SECONDS,
                )
            except TimeoutError:
                continue


def classify_telegram_failure(exc: BaseException) -> TelegramFailure:
    if isinstance(exc, TelegramRetryAfter):
        return TelegramFailure(
            retryable=True,
            category="rate_limited",
            retry_after_seconds=max(0, int(exc.retry_after)),
        )
    if isinstance(exc, TelegramServerError):
        return TelegramFailure(retryable=True, category="server_error")
    if isinstance(exc, TelegramNetworkError | TimeoutError | OSError):
        return TelegramFailure(retryable=True, category="network_error")
    if isinstance(exc, TelegramMigrateToChat):
        return TelegramFailure(retryable=False, category="chat_migrated")
    if isinstance(exc, TelegramForbiddenError):
        return TelegramFailure(retryable=False, category="forbidden")
    if isinstance(exc, TelegramNotFound):
        return TelegramFailure(retryable=False, category="not_found")
    if isinstance(exc, TelegramEntityTooLarge):
        return TelegramFailure(retryable=False, category="payload_too_large")
    if isinstance(exc, TelegramUnauthorizedError):
        return TelegramFailure(retryable=False, category="unauthorized")
    if isinstance(exc, TelegramBadRequest):
        return TelegramFailure(retryable=False, category="bad_request")
    if isinstance(exc, TelegramAPIError):
        return TelegramFailure(retryable=False, category="api_error")
    return TelegramFailure(retryable=False, category="unknown_error")
