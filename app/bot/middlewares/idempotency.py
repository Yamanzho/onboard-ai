from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.bot.api.client import OnboardApiClient

logger = logging.getLogger("app.bot.idempotency")


class TelegramUpdateIdempotencyMiddleware(BaseMiddleware):
    """Claim every Telegram update durably before any handler side effect."""

    def __init__(self, api_client: OnboardApiClient) -> None:
        self._api_client = api_client

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Update):
            raise RuntimeError("Telegram idempotency middleware requires an Update")

        claim = await self._api_client.claim_telegram_update(
            update_id=event.update_id,
            update_type=event.event_type,
        )
        if not claim.acquired or claim.owner_token is None:
            logger.info(
                "telegram_update update_id=%s update_type=%s outcome=duplicate_%s",
                event.update_id,
                event.event_type,
                claim.state,
            )
            return None

        context_token = self._api_client.bind_telegram_update(event.update_id)
        try:
            result = await handler(event, data)
        except Exception:
            await self._fail_claimed(event, claim)
            raise
        except BaseException:
            await self._fail_claimed(event, claim)
            raise
        else:
            updated = await self._api_client.complete_telegram_update(
                receipt_id=claim.receipt_id,
                owner_token=claim.owner_token,
            )
            logger.info(
                "telegram_update update_id=%s update_type=%s outcome=%s",
                event.update_id,
                event.event_type,
                "completed" if updated else "ownership_lost",
            )
            return result
        finally:
            self._api_client.reset_telegram_update(context_token)

    async def _fail_claimed(self, event: Update, claim: object) -> None:
        owner_token = getattr(claim, "owner_token", None)
        receipt_id = getattr(claim, "receipt_id", None)
        if owner_token is None or receipt_id is None:
            return
        try:
            await self._api_client.fail_telegram_update(
                receipt_id=receipt_id,
                owner_token=owner_token,
            )
        except Exception:
            logger.exception(
                "telegram_update update_id=%s update_type=%s "
                "outcome=fail_transition_error",
                event.update_id,
                event.event_type,
            )
