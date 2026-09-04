from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.core.exceptions import ConflictError, ValidationError
from app.core.metrics import OUTBOUND_TRANSITIONS
from app.core.request_id import request_id_log_value
from app.db.models.telegram_outbound_message import TelegramOutboundMessage
from app.db.uow import UnitOfWork

logger = logging.getLogger("app.telegram.outbound")

OUTBOUND_LEASE_SECONDS = 120
OUTBOUND_MAX_ATTEMPTS = 8
OUTBOUND_BATCH_SIZE = 20
OUTBOUND_BASE_BACKOFF_SECONDS = 2
OUTBOUND_MAX_BACKOFF_SECONDS = 300
OUTBOUND_MAX_RETRY_AFTER_SECONDS = 3600
OUTBOUND_SOURCE_TYPES = frozenset(
    {
        "ai_chat",
        "quiz_result",
        "assignment_initial",
        "assignment_reminder",
        "assignment_manual_reminder",
    }
)
ASSIGNMENT_OUTBOUND_SOURCE_TYPES = frozenset(
    {
        "assignment_initial",
        "assignment_reminder",
        "assignment_manual_reminder",
    }
)
_SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")
_ERROR_CATEGORY_RE = re.compile(r"^[a-z0-9_]{1,32}$")


@dataclass(frozen=True, slots=True)
class OutboundDelivery:
    state: str
    message_id: UUID | None
    owner_token: UUID | None
    company_id: UUID | None
    employee_id: UUID | None
    chat_id: int | None
    source_type: str | None
    source_key: str | None
    body: str | None
    parse_mode: str | None
    attempt_count: int
    telegram_message_id: int | None = None

    @classmethod
    def from_model(
        cls,
        row: TelegramOutboundMessage,
        *,
        state: str,
        owner_token: UUID | None = None,
    ) -> OutboundDelivery:
        return cls(
            state=state,
            message_id=row.id,
            owner_token=owner_token,
            company_id=row.company_id,
            employee_id=row.employee_id,
            chat_id=row.chat_id,
            source_type=row.source_type,
            source_key=row.source_key,
            body=row.body,
            parse_mode=row.parse_mode,
            attempt_count=row.attempt_count,
            telegram_message_id=row.telegram_message_id,
        )

    @classmethod
    def not_found(cls) -> OutboundDelivery:
        return cls(
            state="not_found",
            message_id=None,
            owner_token=None,
            company_id=None,
            employee_id=None,
            chat_id=None,
            source_type=None,
            source_key=None,
            body=None,
            parse_mode=None,
            attempt_count=0,
        )


class TelegramOutboundService:
    """Create tenant-owned sends and coordinate platform delivery workers."""

    async def enqueue_for_employee(
        self,
        *,
        company_id: UUID,
        employee_id: UUID,
        source_type: str,
        source_key: str,
        body: str,
    ) -> TelegramOutboundMessage:
        async with UnitOfWork() as uow:
            await uow.enter_tenant(company_id)
            employee = await uow.employees.get_by_id(employee_id)
            if (
                employee is None
                or employee.company_id != company_id
                or employee.telegram_chat_id is None
            ):
                raise ValidationError("Employee has no linked Telegram chat")
            row = await self.enqueue_in_uow(
                uow,
                company_id=company_id,
                employee_id=employee_id,
                chat_id=employee.telegram_chat_id,
                source_type=source_type,
                source_key=source_key,
                body=body,
            )
            await uow.commit()
            return row

    async def enqueue_in_uow(
        self,
        uow: UnitOfWork,
        *,
        company_id: UUID,
        employee_id: UUID,
        chat_id: int,
        source_type: str,
        source_key: str,
        body: str,
        parse_mode: str | None = "HTML",
    ) -> TelegramOutboundMessage:
        source_type, source_key, body, parse_mode = _validate_outbound(
            source_type=source_type,
            source_key=source_key,
            body=body,
            parse_mode=parse_mode,
        )
        now = datetime.now(UTC)
        requested = TelegramOutboundMessage(
            id=uuid4(),
            company_id=company_id,
            employee_id=employee_id,
            chat_id=chat_id,
            source_type=source_type,
            source_key=source_key,
            body=body,
            parse_mode=parse_mode,
            status="pending",
            attempt_count=0,
            next_attempt_at=now,
        )
        stored = await uow.telegram_outbound.enqueue(requested)
        if (
            stored.company_id != company_id
            or stored.employee_id != employee_id
            or stored.chat_id != chat_id
            or stored.body != body
            or stored.parse_mode != parse_mode
        ):
            raise ConflictError(
                "Telegram outbound source was already used for different content"
            )
        return stored

    async def claim_source(
        self,
        *,
        source_type: str,
        source_key: str,
    ) -> OutboundDelivery:
        _validate_source(source_type, source_key)
        now = datetime.now(UTC)
        owner_token = uuid4()
        async with UnitOfWork() as uow:
            await uow.enter_platform()
            await uow.telegram_outbound.expire_exhausted_stale(
                now=now,
                max_attempts=OUTBOUND_MAX_ATTEMPTS,
            )
            claim = await uow.telegram_outbound.claim_source(
                source_type=source_type,
                source_key=source_key,
                owner_token=owner_token,
                now=now,
                lease_expires_at=now
                + timedelta(seconds=OUTBOUND_LEASE_SECONDS),
                max_attempts=OUTBOUND_MAX_ATTEMPTS,
            )
            await uow.commit()
        if claim.message is None:
            return OutboundDelivery.not_found()
        delivery = OutboundDelivery.from_model(
            claim.message,
            state=claim.state,
            owner_token=owner_token if claim.state == "acquired" else None,
        )
        self._log(delivery)
        return delivery

    async def claim_due_batch(
        self,
        *,
        limit: int = OUTBOUND_BATCH_SIZE,
    ) -> list[OutboundDelivery]:
        bounded_limit = max(1, min(limit, OUTBOUND_BATCH_SIZE))
        now = datetime.now(UTC)
        owner_token = uuid4()
        async with UnitOfWork() as uow:
            await uow.enter_platform()
            await uow.telegram_outbound.expire_exhausted_stale(
                now=now,
                max_attempts=OUTBOUND_MAX_ATTEMPTS,
            )
            rows = await uow.telegram_outbound.claim_due_batch(
                owner_token=owner_token,
                now=now,
                lease_expires_at=now
                + timedelta(seconds=OUTBOUND_LEASE_SECONDS),
                max_attempts=OUTBOUND_MAX_ATTEMPTS,
                limit=bounded_limit,
            )
            await uow.commit()
        deliveries = [
            OutboundDelivery.from_model(
                row,
                state="acquired",
                owner_token=owner_token,
            )
            for row in rows
        ]
        for delivery in deliveries:
            self._log(delivery)
        return deliveries

    async def mark_sent(
        self,
        *,
        message_id: UUID,
        owner_token: UUID,
        telegram_message_id: int,
    ) -> bool:
        now = datetime.now(UTC)
        async with UnitOfWork() as uow:
            await uow.enter_platform()
            row = await uow.telegram_outbound.mark_sent(
                message_id=message_id,
                owner_token=owner_token,
                telegram_message_id=telegram_message_id,
                sent_at=now,
            )
            await uow.commit()
        if row is not None:
            self._log(OutboundDelivery.from_model(row, state="sent"))
        return row is not None

    async def mark_failed(
        self,
        *,
        message_id: UUID,
        owner_token: UUID,
        retryable: bool,
        error_category: str,
        retry_after_seconds: int | None = None,
    ) -> bool:
        category = error_category.strip().lower()
        if not _ERROR_CATEGORY_RE.fullmatch(category):
            raise ValidationError("Telegram error category is invalid")
        now = datetime.now(UTC)
        async with UnitOfWork() as uow:
            await uow.enter_platform()
            current = await uow.telegram_outbound.get_by_id(message_id)
            if current is None:
                await uow.commit()
                return False
            should_retry = (
                retryable
                and current.attempt_count < OUTBOUND_MAX_ATTEMPTS
            )
            delay = _retry_delay_seconds(
                attempt_count=current.attempt_count,
                retry_after_seconds=retry_after_seconds,
            )
            row = await uow.telegram_outbound.mark_failed(
                message_id=message_id,
                owner_token=owner_token,
                retryable=should_retry,
                next_attempt_at=now + timedelta(seconds=delay),
                error_category=category,
            )
            await uow.commit()
        if row is not None:
            self._log(
                OutboundDelivery.from_model(
                    row,
                    state="pending" if should_retry else "failed",
                ),
                error_category=category,
            )
        return row is not None

    @staticmethod
    def _log(
        delivery: OutboundDelivery,
        *,
        error_category: str | None = None,
    ) -> None:
        metric_status = delivery.state if delivery.state in {
            "acquired",
            "pending",
            "sending",
            "sent",
            "failed",
            "not_found",
        } else "unknown"
        metric_error = error_category or "none"
        OUTBOUND_TRANSITIONS.labels(
            status=metric_status,
            error_category=metric_error,
        ).inc()
        logger.info(
            "telegram_outbound request_id=%s outbound_message_id=%s "
            "company_id=%s employee_id=%s source_type=%s source_key=%s "
            "attempt=%s status=%s error_category=%s",
            request_id_log_value(),
            delivery.message_id or "",
            delivery.company_id or "",
            delivery.employee_id or "",
            delivery.source_type or "",
            delivery.source_key or "",
            delivery.attempt_count,
            delivery.state,
            error_category or "",
        )


def _validate_source(source_type: str, source_key: str) -> tuple[str, str]:
    normalized_type = source_type.strip().lower()
    normalized_key = source_key.strip()
    if normalized_type not in OUTBOUND_SOURCE_TYPES:
        raise ValidationError("Telegram outbound source type is invalid")
    if not _SOURCE_KEY_RE.fullmatch(normalized_key):
        raise ValidationError("Telegram outbound source key is invalid")
    return normalized_type, normalized_key


def _validate_outbound(
    *,
    source_type: str,
    source_key: str,
    body: str,
    parse_mode: str | None,
) -> tuple[str, str, str, str | None]:
    normalized_type, normalized_key = _validate_source(source_type, source_key)
    normalized_body = body.strip()
    if not normalized_body or len(normalized_body) > 4096:
        raise ValidationError("Telegram outbound body must contain 1-4096 characters")
    if parse_mode not in {None, "HTML"}:
        raise ValidationError("Telegram outbound parse mode is invalid")
    return normalized_type, normalized_key, normalized_body, parse_mode


def _retry_delay_seconds(
    *,
    attempt_count: int,
    retry_after_seconds: int | None,
) -> int:
    exponent = max(0, min(attempt_count - 1, 20))
    backoff = min(
        OUTBOUND_BASE_BACKOFF_SECONDS * (2**exponent),
        OUTBOUND_MAX_BACKOFF_SECONDS,
    )
    if retry_after_seconds is None:
        return backoff
    retry_after = max(
        0,
        min(retry_after_seconds, OUTBOUND_MAX_RETRY_AFTER_SECONDS),
    )
    return max(backoff, retry_after)
