"""Telegram → POST /api/v1/ai/chat. Not an ACL layer and not an LLM client."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from app.bot.api.client import OnboardApiClient, OnboardApiError
from app.bot.services.ai_conversation import (
    TelegramConversationStore,
    get_telegram_conversation_store,
)
from app.core.exceptions import ServiceUnavailableError
from app.services.telegram_format import format_ai_reply

logger = logging.getLogger(__name__)

MSG_UNAUTHENTICATED = (
    "Вы ещё не добавлены в OnboardAI.\n"
    "Обратитесь к HR, чтобы вас зарегистрировали."
)
MSG_FORBIDDEN = "У вас нет доступа к AI-помощнику."
MSG_RATE_LIMITED = "Слишком много вопросов. Попробуйте позже."
MSG_UNAVAILABLE = "Сервис временно недоступен. Попробуйте позже."
MSG_TIMEOUT = "Не удалось получить ответ. Попробуйте ещё раз."
MSG_INTERNAL = "Произошла внутренняя ошибка. Попробуйте позже."
MSG_VALIDATION = "Не удалось обработать вопрос. Сократите текст и попробуйте снова."
MSG_NEW_CHAT = "Начинаем новый диалог."
def user_error_message(exc: BaseException) -> str:
    """Map upstream failures to a short user-facing line. Never echo bodies."""
    if isinstance(exc, ServiceUnavailableError):
        return MSG_UNAVAILABLE
    if isinstance(exc, httpx.TimeoutException):
        return MSG_TIMEOUT
    if isinstance(exc, httpx.HTTPError):
        return MSG_UNAVAILABLE
    if isinstance(exc, OnboardApiError):
        status = exc.status_code
        if status in {401, 404}:
            return MSG_UNAUTHENTICATED
        if status == 403:
            return MSG_FORBIDDEN
        if status == 422:
            return MSG_VALIDATION
        if status == 429:
            if exc.retry_after is not None and exc.retry_after > 0:
                return (
                    f"Слишком много вопросов. Попробуйте через {exc.retry_after} сек."
                )
            return MSG_RATE_LIMITED
        if status == 503:
            return MSG_UNAVAILABLE
        if status is not None and status >= 500:
            return MSG_INTERNAL
        return MSG_INTERNAL
    return MSG_INTERNAL


async def ask_company_knowledge(
    api: OnboardApiClient,
    message: str,
    *,
    telegram_user_id: int | None = None,
    conversations: TelegramConversationStore | None = None,
) -> str:
    """Call the chat API and return Telegram HTML.

    Identity is the bound employee JWT. This function never sends tenant,
    employee, or role selectors in the request body. conversation_id is an
    opaque pointer from Redis / the previous HTTP response.
    """
    store = conversations
    conversation_id: UUID | None = None
    if telegram_user_id is not None:
        store = store or get_telegram_conversation_store()
        try:
            conversation_id = await store.get_current_conversation(telegram_user_id)
        except ServiceUnavailableError as exc:
            return user_error_message(exc)

    try:
        payload = await _post_ai_chat(api, message, conversation_id)
    except (
        OnboardApiError,
        httpx.TimeoutException,
        httpx.HTTPError,
        ServiceUnavailableError,
    ) as exc:
        logger.warning(
            "telegram_ai_chat_failed error_type=%s status_code=%s request_id=%s",
            type(exc).__name__,
            getattr(exc, "status_code", None),
            getattr(exc, "request_id", None) or "-",
        )
        return user_error_message(exc)
    except Exception:
        logger.warning("telegram_ai_chat_failed error_type=Exception")
        return MSG_INTERNAL

    if not isinstance(payload, dict):
        return MSG_INTERNAL
    if store is not None and telegram_user_id is not None:
        await _remember_conversation(store, telegram_user_id, payload)
    return format_ai_reply(payload)


async def ask_assistant(
    api: OnboardApiClient,
    message: str,
    *,
    telegram_user_id: int | None = None,
    conversations: TelegramConversationStore | None = None,
) -> dict[str, Any]:
    """Call the orchestrated assistant and remember conversation_id if present."""
    store = conversations
    conversation_id: UUID | None = None
    if telegram_user_id is not None:
        store = store or get_telegram_conversation_store()
        try:
            conversation_id = await store.get_current_conversation(telegram_user_id)
        except ServiceUnavailableError as exc:
            return {"text": user_error_message(exc), "action": "none", "error": True}

    try:
        payload = await _post_assistant_chat(api, message, conversation_id)
    except (
        OnboardApiError,
        httpx.TimeoutException,
        httpx.HTTPError,
        ServiceUnavailableError,
    ) as exc:
        logger.warning(
            "telegram_assistant_failed error_type=%s status_code=%s request_id=%s",
            type(exc).__name__,
            getattr(exc, "status_code", None),
            getattr(exc, "request_id", None) or "-",
        )
        return {"text": user_error_message(exc), "action": "none", "error": True}
    except Exception:
        logger.warning("telegram_assistant_failed error_type=Exception")
        return {"text": MSG_INTERNAL, "action": "none", "error": True}

    if not isinstance(payload, dict):
        return {"text": MSG_INTERNAL, "action": "none", "error": True}
    if store is not None and telegram_user_id is not None:
        await _remember_conversation(store, telegram_user_id, payload)
    return payload


async def _post_ai_chat(
    api: OnboardApiClient,
    message: str,
    conversation_id: UUID | None,
) -> dict:
    if conversation_id is None:
        return await api.post_ai_chat(message)
    return await api.post_ai_chat(message, conversation_id=conversation_id)


async def _post_assistant_chat(
    api: OnboardApiClient,
    message: str,
    conversation_id: UUID | None,
) -> dict:
    if conversation_id is None:
        return await api.post_assistant_chat(message)
    return await api.post_assistant_chat(message, conversation_id=conversation_id)


async def _remember_conversation(
    store: TelegramConversationStore,
    telegram_user_id: int,
    payload: dict[str, Any],
) -> None:
    raw = payload.get("conversation_id")
    if raw is None:
        return
    try:
        conversation_id = raw if isinstance(raw, UUID) else UUID(str(raw))
    except (TypeError, ValueError):
        return
    try:
        await store.set_current_conversation(telegram_user_id, conversation_id)
    except ServiceUnavailableError:
        return
