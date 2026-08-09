"""Sprint 1.1 — invite email delivery truthfulness."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.services.email import EmailService, InviteEmailResult


@pytest.mark.asyncio
async def test_smtp_disabled_returns_manual_url_not_false_success(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    from app.core.config import get_settings

    get_settings.cache_clear()
    token = f"tok-{uuid4().hex}"
    invite_url = f"https://example.test/invite#{token}"
    service = EmailService()
    with caplog.at_level(logging.INFO, logger="app.email"):
        result = await service.send_invite_email(
            to_email="a@example.com",
            full_name="A",
            invite_url=invite_url,
            company_name="Co",
        )
    assert isinstance(result, InviteEmailResult)
    assert result.email_sent is False
    assert result.delivery == "manual_url"
    assert result.invite_url == invite_url
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert token not in joined
    assert "email sent" not in joined.lower() or "not sent" in joined.lower()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_smtp_configured_attempts_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "pass")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.test")
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()

    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_instance.__exit__.return_value = False

    with patch("app.services.email.smtplib.SMTP", return_value=smtp_instance) as smtp_cls:
        result = await EmailService().send_invite_email(
            to_email="a@example.com",
            full_name="A",
            invite_url="https://example.test/invite#secret-token-value",
            company_name="Co",
        )

    smtp_cls.assert_called_once()
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("user", "pass")
    smtp_instance.send_message.assert_called_once()
    assert result.email_sent is True
    assert result.delivery == "email"
    assert result.invite_url is None
    get_settings.cache_clear()
