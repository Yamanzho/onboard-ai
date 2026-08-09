"""Sprint 1.1 — invite email delivery truthfulness."""

from __future__ import annotations

import logging
import smtplib
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.db.enums import InvitePurpose
from app.services.email import EmailService, InviteEmailResult, build_invite_email_copy


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


def _configure_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user")
    monkeypatch.setenv("SMTP_PASSWORD", "super-secret-smtp-password")
    monkeypatch.setenv("SMTP_FROM", "noreply@example.test")
    monkeypatch.setenv("SMTP_USE_TLS", "true")


@pytest.mark.asyncio
async def test_smtp_configured_attempts_send(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_smtp(monkeypatch)
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
    smtp_instance.login.assert_called_once_with("user", "super-secret-smtp-password")
    smtp_instance.send_message.assert_called_once()
    assert result.email_sent is True
    assert result.delivery == "email"
    assert result.invite_url is None
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_smtp_failure_returns_manual_url_not_success(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_smtp(monkeypatch)
    from app.core.config import get_settings

    get_settings.cache_clear()
    token = f"fail-tok-{uuid4().hex}"
    invite_url = f"https://example.test/invite#{token}"
    password = "super-secret-smtp-password"

    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_instance.__exit__.return_value = False
    smtp_instance.send_message.side_effect = smtplib.SMTPServerDisconnected(
        "Connection unexpectedly closed"
    )

    with (
        patch("app.services.email.smtplib.SMTP", return_value=smtp_instance),
        caplog.at_level(logging.WARNING, logger="app.email"),
    ):
        result = await EmailService().send_invite_email(
            to_email="a@example.com",
            full_name="A",
            invite_url=invite_url,
            company_name="Co",
        )

    assert result.email_sent is False
    assert result.delivery == "manual_url"
    assert result.invite_url == invite_url
    assert "could not be delivered" in result.detail.lower()
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert token not in joined
    assert password not in joined
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_smtp_auth_failure_does_not_claim_success_or_log_password(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_smtp(monkeypatch)
    from app.core.config import get_settings

    get_settings.cache_clear()
    password = "super-secret-smtp-password"

    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_instance.__exit__.return_value = False
    smtp_instance.login.side_effect = smtplib.SMTPAuthenticationError(
        535, b"Authentication failed"
    )

    with (
        patch("app.services.email.smtplib.SMTP", return_value=smtp_instance),
        caplog.at_level(logging.WARNING, logger="app.email"),
    ):
        result = await EmailService().send_invite_email(
            to_email="a@example.com",
            full_name="A",
            invite_url="https://example.test/invite#tok",
            company_name="Co",
        )

    assert result.email_sent is False
    assert result.delivery == "manual_url"
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert password not in joined
    get_settings.cache_clear()


def test_employee_email_template_contains_accept_and_telegram() -> None:
    copy = build_invite_email_copy(
        purpose=InvitePurpose.EMPLOYEE.value,
        full_name="Alex",
        company_name="Acme",
        invite_url="https://example.test/invite#tok",
        ttl_hours=24,
        telegram_invite_url="https://t.me/OnboardAIBot?start=tok",
    )
    assert copy.subject == "Welcome to OnboardAI — Start your onboarding"
    assert "You have been invited to join Acme" in copy.text_body
    assert "Accept invitation" in copy.html_body
    assert "https://example.test/invite#tok" in copy.text_body
    assert "Open Telegram" in copy.html_body
    assert "https://t.me/OnboardAIBot?start=tok" in copy.text_body
    assert "expires in 24 hours" in copy.text_body


def test_hr_email_template() -> None:
    copy = build_invite_email_copy(
        purpose=InvitePurpose.HR.value,
        full_name="Pat",
        company_name="Acme",
        invite_url="https://example.test/invite#tok",
        ttl_hours=24,
        telegram_invite_url=None,
    )
    assert copy.subject == "You've been invited to join Acme as HR"
    assert "Role: HR" in copy.text_body
    assert "Accept invitation" in copy.html_body
    assert "Open Telegram" not in copy.html_body


def test_admin_email_template() -> None:
    copy = build_invite_email_copy(
        purpose=InvitePurpose.ADMIN.value,
        full_name="Sam",
        company_name="Acme",
        invite_url="https://example.test/invite#tok",
        ttl_hours=12,
        telegram_invite_url=None,
    )
    assert copy.subject == "You've been invited to join Acme as Admin"
    assert "Role: Admin" in copy.text_body
    assert "Accept invitation" in copy.html_body
    assert "expires in 12 hours" in copy.text_body


@pytest.mark.asyncio
async def test_smtp_port_465_uses_ssl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_PORT", "465")
    from app.core.config import get_settings

    get_settings.cache_clear()
    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_instance.__exit__.return_value = False

    with patch("app.services.email.smtplib.SMTP_SSL", return_value=smtp_instance) as ssl_cls:
        with patch("app.services.email.smtplib.SMTP") as plain_cls:
            result = await EmailService().send_invite_email(
                to_email="a@example.com",
                full_name="A",
                invite_url="https://example.test/invite#tok",
                company_name="Co",
            )

    ssl_cls.assert_called_once()
    plain_cls.assert_not_called()
    smtp_instance.starttls.assert_not_called()
    smtp_instance.login.assert_called_once()
    assert result.email_sent is True
    assert result.delivery == "email"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_configured_send_uses_multipart_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_smtp(monkeypatch)
    from app.core.config import get_settings

    get_settings.cache_clear()
    smtp_instance = MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_instance.__exit__.return_value = False
    captured: dict[str, object] = {}

    def _capture(message: object) -> None:
        captured["message"] = message

    smtp_instance.send_message.side_effect = _capture

    with patch("app.services.email.smtplib.SMTP", return_value=smtp_instance):
        await EmailService().send_invite_email(
            to_email="a@example.com",
            full_name="A",
            invite_url="https://example.test/invite#tok",
            company_name="Acme",
            purpose=InvitePurpose.EMPLOYEE.value,
            telegram_invite_url="https://t.me/bot?start=tok",
        )

    message = captured["message"]
    assert message["Subject"] == "Welcome to OnboardAI — Start your onboarding"
    assert message.get_content_type() == "multipart/alternative"
    get_settings.cache_clear()
