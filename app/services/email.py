from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape
from typing import Literal

from app.core.config import get_settings
from app.db.enums import InvitePurpose

logger = logging.getLogger("app.email")

InviteDeliveryMode = Literal["email", "manual_url"]


@dataclass(frozen=True, slots=True)
class InviteEmailResult:
    """Outcome of an invite email attempt — never claims success without SMTP."""

    email_sent: bool
    delivery: InviteDeliveryMode
    invite_url: str | None
    detail: str
    telegram_invite_url: str | None = None


@dataclass(frozen=True, slots=True)
class InviteEmailCopy:
    subject: str
    text_body: str
    html_body: str


def _cta_html(label: str, url: str) -> str:
    safe_label = escape(label)
    safe_url = escape(url, quote=True)
    return (
        f'<p><a href="{safe_url}" style="display:inline-block;padding:10px 16px;'
        f'background:#0f766e;color:#ffffff;text-decoration:none;border-radius:6px;'
        f'font-weight:600;">{safe_label}</a></p>'
        f'<p style="font-size:13px;color:#555;">Or open this link:<br>'
        f'<a href="{safe_url}">{safe_url}</a></p>'
    )


def build_invite_email_copy(
    *,
    purpose: str,
    full_name: str,
    company_name: str,
    invite_url: str,
    ttl_hours: int,
    telegram_invite_url: str | None,
) -> InviteEmailCopy:
    """Build subject + text/HTML bodies for an invitation purpose."""
    safe_name = escape(full_name)
    safe_company = escape(company_name)
    accept = _cta_html("Accept invitation", invite_url)

    if purpose == InvitePurpose.HR.value:
        subject = f"You've been invited to join {company_name} as HR"
        text_body = (
            f"Hello {full_name},\n\n"
            f"You've been invited to join {company_name} as HR in OnboardAI.\n\n"
            f"Role: HR\n"
            f"Click below to accept your invitation:\n{invite_url}\n\n"
            f"This invitation expires in {ttl_hours} hours.\n\n"
            f"— OnboardAI"
        )
        html_body = (
            f"<p>Hello {safe_name},</p>"
            f"<p>You've been invited to join <strong>{safe_company}</strong> "
            f"as <strong>HR</strong> in OnboardAI.</p>"
            f"<p>Role: HR</p>"
            f"{accept}"
            f"<p>This invitation expires in {ttl_hours} hours.</p>"
            f"<p>— OnboardAI</p>"
        )
        return InviteEmailCopy(subject=subject, text_body=text_body, html_body=html_body)

    if purpose == InvitePurpose.ADMIN.value:
        subject = f"You've been invited to join {company_name} as Admin"
        text_body = (
            f"Hello {full_name},\n\n"
            f"You've been invited to join {company_name} as Admin in OnboardAI.\n\n"
            f"Role: Admin\n"
            f"Click below to accept your invitation:\n{invite_url}\n\n"
            f"This invitation expires in {ttl_hours} hours.\n\n"
            f"— OnboardAI"
        )
        html_body = (
            f"<p>Hello {safe_name},</p>"
            f"<p>You've been invited to join <strong>{safe_company}</strong> "
            f"as <strong>Admin</strong> in OnboardAI.</p>"
            f"<p>Role: Admin</p>"
            f"{accept}"
            f"<p>This invitation expires in {ttl_hours} hours.</p>"
            f"<p>— OnboardAI</p>"
        )
        return InviteEmailCopy(subject=subject, text_body=text_body, html_body=html_body)

    # EMPLOYEE (default)
    subject = "Welcome to OnboardAI — Start your onboarding"
    telegram_text = ""
    telegram_html = ""
    if telegram_invite_url:
        telegram_text = (
            "\nAfter accepting, connect your Telegram account to continue "
            "onboarding.\n"
            f"Open Telegram:\n{telegram_invite_url}\n"
        )
        telegram_html = (
            "<p>After accepting, connect your Telegram account to continue "
            "onboarding.</p>"
            f"{_cta_html('Open Telegram', telegram_invite_url)}"
        )
    text_body = (
        f"Hello {full_name},\n\n"
        f"You have been invited to join {company_name} in OnboardAI.\n\n"
        f"Click below to accept your invitation and start onboarding.\n"
        f"{invite_url}\n"
        f"{telegram_text}\n"
        f"This invitation expires in {ttl_hours} hours.\n\n"
        f"— OnboardAI"
    )
    html_body = (
        f"<p>Hello {safe_name},</p>"
        f"<p>You have been invited to join <strong>{safe_company}</strong> "
        f"in OnboardAI.</p>"
        f"<p>Click below to accept your invitation and start onboarding.</p>"
        f"{accept}"
        f"{telegram_html}"
        f"<p>This invitation expires in {ttl_hours} hours.</p>"
        f"<p>— OnboardAI</p>"
    )
    return InviteEmailCopy(subject=subject, text_body=text_body, html_body=html_body)


class EmailService:
    """Send transactional email. Never pretends mail was sent when SMTP is unset."""

    async def send_invite_email(
        self,
        *,
        to_email: str,
        full_name: str,
        invite_url: str,
        company_name: str,
        purpose: str = InvitePurpose.EMPLOYEE.value,
        telegram_invite_url: str | None = None,
    ) -> InviteEmailResult:
        settings = get_settings()
        copy = build_invite_email_copy(
            purpose=purpose,
            full_name=full_name,
            company_name=company_name,
            invite_url=invite_url,
            ttl_hours=settings.invite_ttl_hours,
            telegram_invite_url=telegram_invite_url,
        )
        return await self._send(
            to_email=to_email,
            subject=copy.subject,
            text_body=copy.text_body,
            html_body=copy.html_body,
            invite_url=invite_url,
            telegram_invite_url=telegram_invite_url,
        )

    async def send_password_reset_email(
        self,
        *,
        to_email: str,
        full_name: str,
        reset_url: str,
        company_name: str,
        ttl_hours: int,
    ) -> InviteEmailResult:
        """Send a password-reset link. Never logs the URL/token."""
        safe_name = escape(full_name)
        safe_company = escape(company_name)
        cta = _cta_html("Reset password", reset_url)
        subject = f"Reset your OnboardAI password — {company_name}"
        text_body = (
            f"Hello {full_name},\n\n"
            f"A password reset was requested for your OnboardAI account "
            f"at {company_name}.\n\n"
            f"Open this link to set a new password:\n{reset_url}\n\n"
            f"This link expires in {ttl_hours} hours. "
            f"If you did not request this, you can ignore this email.\n\n"
            f"— OnboardAI"
        )
        html_body = (
            f"<p>Hello {safe_name},</p>"
            f"<p>A password reset was requested for your OnboardAI account "
            f"at <strong>{safe_company}</strong>.</p>"
            f"{cta}"
            f"<p>This link expires in {ttl_hours} hours. "
            f"If you did not request this, you can ignore this email.</p>"
            f"<p>— OnboardAI</p>"
        )
        return await self._send(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            invite_url=reset_url,
            telegram_invite_url=None,
        )

    async def _send(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str,
        invite_url: str,
        telegram_invite_url: str | None = None,
    ) -> InviteEmailResult:
        settings = get_settings()
        if not settings.smtp_host.strip():
            # Never log body — invite emails contain one-time tokens.
            logger.info(
                "email not sent (SMTP not configured) to=%s subject=%r "
                "delivery=manual_url body_omitted=true",
                to_email,
                subject,
            )
            return InviteEmailResult(
                email_sent=False,
                delivery="manual_url",
                invite_url=invite_url,
                telegram_invite_url=telegram_invite_url,
                detail=(
                    "SMTP is not configured; invite was created — "
                    "share the invite URL manually"
                ),
            )

        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

        try:
            # Port 465 = implicit SSL (common for PS.KZ / many hosts).
            # Port 587 = SMTP + STARTTLS when SMTP_USE_TLS=true.
            if settings.smtp_port == 465:
                with smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port, timeout=15
                ) as smtp:
                    if settings.smtp_user:
                        smtp.login(settings.smtp_user, settings.smtp_password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(
                    settings.smtp_host, settings.smtp_port, timeout=15
                ) as smtp:
                    if settings.smtp_use_tls:
                        smtp.starttls()
                    if settings.smtp_user:
                        smtp.login(settings.smtp_user, settings.smtp_password)
                    smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            # Do not log exception text — some SMTP servers echo credentials.
            logger.warning(
                "email send failed to=%s subject=%r delivery=manual_url "
                "error_type=%s body_omitted=true",
                to_email,
                subject,
                type(exc).__name__,
            )
            return InviteEmailResult(
                email_sent=False,
                delivery="manual_url",
                invite_url=invite_url,
                telegram_invite_url=telegram_invite_url,
                detail=(
                    "Invite email could not be delivered; "
                    "share the invite URL manually"
                ),
            )

        logger.info(
            "email sent to=%s subject=%r delivery=email body_omitted=true",
            to_email,
            subject,
        )
        return InviteEmailResult(
            email_sent=True,
            delivery="email",
            invite_url=None,
            telegram_invite_url=telegram_invite_url,
            detail="Invite email sent",
        )
