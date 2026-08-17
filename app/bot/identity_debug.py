"""TEMPORARY Telegram identity debug (BOT_IDENTITY_DEBUG=true).

Logs only: handler, telegram_user_id, chat_id, employee_id, company_id,
lookup result, HTTP status. Never logs tokens, passwords, or invite secrets.
"""

from __future__ import annotations

import logging
import os
from uuid import UUID

logger = logging.getLogger("app.bot.identity_debug")

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def identity_debug_enabled() -> bool:
    return os.environ.get("BOT_IDENTITY_DEBUG", "").strip().lower() in _TRUTHY


def log_identity(
    *,
    handler: str,
    telegram_user_id: int | None,
    result: str,
    chat_id: int | None = None,
    employee_id: UUID | str | None = None,
    company_id: UUID | str | None = None,
    status_code: int | None = None,
) -> None:
    if not identity_debug_enabled():
        return
    logger.info(
        "telegram_identity handler=%s telegram_user_id=%s chat_id=%s "
        "result=%s employee_id=%s company_id=%s status_code=%s",
        handler,
        telegram_user_id,
        chat_id,
        result,
        employee_id,
        company_id,
        status_code,
    )
