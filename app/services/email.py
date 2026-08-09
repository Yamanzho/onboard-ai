from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
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


def _purpose_copy(
    *,
    purpose: str,
    full_name: str,
    company_name: str,
    invite_url: str,
    ttl_hours: int,
    telegram_invite_url: str | None,
) -> tuple[str, str]:
    """Return (subject, body) for the invitation purpose."""
    if purpose == InvitePurpose.HR.value:
        subject = f"You've been invited to join {company_name} as HR"
        body = (
            f"Hello {full_name},\n\n"
            f"You've been invited to join {company_name} as an HR administrator "
            f"in OnboardAI.\n\n"
            f"Accept invitation:\n{invite_url}\n\n"
            f"This link expires in {ttl_hours} hours.\n\n"
            f"— OnboardAI"
        )
        return subject, body
    if purpose == InvitePurpose.ADMIN.value:
        subject = f"You've been invited to join {company_name} as Admin"
        body = (
            f"Hello {full_name},\n\n"
            f"You've been invited to join {company_name} as an Admin "
            f"in OnboardAI.\n\n"
            f"Accept invitation:\n{invite_url}\n\n"
            f"This link expires in {ttl_hours} hours.\n\n"
            f"— OnboardAI"
        )
        return subject, body

    # EMPLOYEE (default)
    subject = f"Welcome to {company_name} — start your onboarding"
    telegram_line = ""
    if telegram_invite_url:
        telegram_line = f"\nOpen Telegram:\n{telegram_invite_url}\n"
    body = (
        f"Hello {full_name},\n\n"
        f"Welcome to {company_name}. You've been invited to start onboarding "
        f"in OnboardAI.\n\n"
        f"Accept invitation (set your password):\n{invite_url}\n"
        f"{telegram_line}\n"
        f"This link expires in {ttl_hours} hours.\n\n"
        f"— OnboardAI"
    )
    return subject, body


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
        subject, body = _purpose_copy(
            purpose=purpose,
            full_name=full_name,
            company_name=company_name,
            invite_url=invite_url,
            ttl_hours=settings.invite_ttl_hours,
            telegram_invite_url=telegram_invite_url,
        )
        return await self._send(
            to_email=to_email,
            subject=subject,
            body=body,
            invite_url=invite_url,
            telegram_invite_url=telegram_invite_url,
        )

    async def _send(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
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
        message.set_content(body)

        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
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
