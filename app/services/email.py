from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger("app.email")


class EmailService:
    """Send transactional email. Falls back to logging when SMTP is not configured."""

    async def send_invite_email(
        self,
        *,
        to_email: str,
        full_name: str,
        invite_url: str,
        company_name: str,
    ) -> None:
        subject = f"Приглашение в OnboardAI — {company_name}"
        body = (
            f"Здравствуйте, {full_name}!\n\n"
            f"Вас пригласили в компанию «{company_name}» в OnboardAI.\n"
            f"Перейдите по ссылке, чтобы установить пароль и активировать аккаунт:\n\n"
            f"{invite_url}\n\n"
            f"Ссылка действительна 24 часа.\n\n"
            f"— OnboardAI"
        )
        await self._send(to_email=to_email, subject=subject, body=body)

    async def _send(self, *, to_email: str, subject: str, body: str) -> None:
        settings = get_settings()
        if not settings.smtp_host:
            # Never log body — invite emails contain one-time tokens.
            logger.info(
                "email skipped (SMTP not configured) to=%s subject=%r body_omitted=true",
                to_email,
                subject,
            )
            return

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
        logger.info("email sent to=%s subject=%r", to_email, subject)
