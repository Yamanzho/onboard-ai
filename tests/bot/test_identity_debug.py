from __future__ import annotations

import logging

import pytest

from app.bot.identity_debug import identity_debug_enabled, log_identity

pytestmark = [pytest.mark.security, pytest.mark.telegram]


def test_identity_debug_off_by_default(monkeypatch, caplog) -> None:
    monkeypatch.delenv("BOT_IDENTITY_DEBUG", raising=False)
    assert identity_debug_enabled() is False
    with caplog.at_level(logging.INFO, logger="app.bot.identity_debug"):
        log_identity(
            handler="profile_view",
            telegram_user_id=42,
            chat_id=42,
            result="NOT_FOUND",
        )
    assert caplog.records == []


def test_identity_debug_logs_ids_not_secrets(monkeypatch, caplog) -> None:
    monkeypatch.setenv("BOT_IDENTITY_DEBUG", "true")
    with caplog.at_level(logging.INFO, logger="app.bot.identity_debug"):
        log_identity(
            handler="profile_view",
            telegram_user_id=9400000042,
            chat_id=9400000042,
            result="NOT_FOUND",
            company_id="11111111-1111-4111-8111-111111111111",
            status_code=404,
        )
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "telegram_identity" in message
    assert "handler=profile_view" in message
    assert "telegram_user_id=9400000042" in message
    assert "result=NOT_FOUND" in message
    assert "token" not in message.lower()
    assert "password" not in message.lower()
    assert "invite" not in message.lower()
