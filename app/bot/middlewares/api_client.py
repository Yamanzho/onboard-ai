from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from app.bot.api.client import OnboardApiClient


class ApiClientMiddleware(BaseMiddleware):
    """Inject OnboardApiClient into handler dependencies."""

    def __init__(self, api_client: OnboardApiClient) -> None:
        self._api_client = api_client

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["api"] = self._api_client
        return await handler(event, data)
