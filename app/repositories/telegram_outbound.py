from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.telegram_outbound_message import TelegramOutboundMessage
from app.repositories.base import BaseRepository

OutboundClaimState = Literal[
    "acquired",
    "pending",
    "sending",
    "sent",
    "failed",
    "not_found",
]


@dataclass(frozen=True, slots=True)
class OutboundClaim:
    state: OutboundClaimState
    message: TelegramOutboundMessage | None


class TelegramOutboundRepository(BaseRepository[TelegramOutboundMessage]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TelegramOutboundMessage)

    async def enqueue(
        self,
        message: TelegramOutboundMessage,
    ) -> TelegramOutboundMessage:
        self._ensure_rls_context()
        statement = (
            insert(TelegramOutboundMessage)
            .values(
                id=message.id,
                company_id=message.company_id,
                employee_id=message.employee_id,
                chat_id=message.chat_id,
                source_type=message.source_type,
                source_key=message.source_key,
                body=message.body,
                parse_mode=message.parse_mode,
                status="pending",
                attempt_count=0,
                next_attempt_at=message.next_attempt_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_telegram_outbound_source",
            )
            .returning(TelegramOutboundMessage)
        )
        inserted = (await self._session.scalars(statement)).first()
        if inserted is not None:
            return inserted
        existing = await self.get_by_source(
            source_type=message.source_type,
            source_key=message.source_key,
        )
        if existing is None:
            raise RuntimeError("Telegram outbound conflict was not visible")
        return existing

    async def get_by_source(
        self,
        *,
        source_type: str,
        source_key: str,
    ) -> TelegramOutboundMessage | None:
        self._ensure_rls_context()
        statement = select(TelegramOutboundMessage).where(
            TelegramOutboundMessage.source_type == source_type,
            TelegramOutboundMessage.source_key == source_key,
        )
        return (await self._session.scalars(statement)).first()

    async def claim_source(
        self,
        *,
        source_type: str,
        source_key: str,
        owner_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
        max_attempts: int,
    ) -> OutboundClaim:
        self._ensure_rls_context()
        message = TelegramOutboundMessage
        claimable = and_(
            message.attempt_count < max_attempts,
            or_(
                and_(
                    message.status == "pending",
                    message.next_attempt_at <= now,
                ),
                and_(
                    message.status == "sending",
                    message.lease_expires_at < now,
                ),
            ),
        )
        statement = (
            update(message)
            .where(
                message.source_type == source_type,
                message.source_key == source_key,
                claimable,
            )
            .values(
                status="sending",
                owner_token=owner_token,
                lease_expires_at=lease_expires_at,
                last_attempt_at=now,
                attempt_count=message.attempt_count + 1,
                last_error_category=None,
                updated_at=func.now(),
            )
            .returning(message)
        )
        claimed = (await self._session.scalars(statement)).first()
        if claimed is not None:
            return OutboundClaim(state="acquired", message=claimed)
        existing = await self.get_by_source(
            source_type=source_type,
            source_key=source_key,
        )
        if existing is None:
            return OutboundClaim(state="not_found", message=None)
        return OutboundClaim(
            state=existing.status,  # type: ignore[arg-type]
            message=existing,
        )

    async def claim_due_batch(
        self,
        *,
        owner_token: UUID,
        now: datetime,
        lease_expires_at: datetime,
        max_attempts: int,
        limit: int,
    ) -> list[TelegramOutboundMessage]:
        self._ensure_rls_context()
        message = TelegramOutboundMessage
        claimable = and_(
            message.attempt_count < max_attempts,
            or_(
                and_(
                    message.status == "pending",
                    message.next_attempt_at <= now,
                ),
                and_(
                    message.status == "sending",
                    message.lease_expires_at < now,
                ),
            ),
        )
        candidates = (
            select(message.id)
            .where(claimable)
            .order_by(
                func.coalesce(
                    message.next_attempt_at,
                    message.lease_expires_at,
                ),
                message.created_at,
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
            .cte("telegram_outbound_candidates")
        )
        statement = (
            update(message)
            .where(message.id.in_(select(candidates.c.id)))
            .values(
                status="sending",
                owner_token=owner_token,
                lease_expires_at=lease_expires_at,
                last_attempt_at=now,
                attempt_count=message.attempt_count + 1,
                last_error_category=None,
                updated_at=func.now(),
            )
            .returning(message)
        )
        return list((await self._session.scalars(statement)).all())

    async def expire_exhausted_stale(
        self,
        *,
        now: datetime,
        max_attempts: int,
    ) -> int:
        self._ensure_rls_context()
        statement = (
            update(TelegramOutboundMessage)
            .where(
                TelegramOutboundMessage.status == "sending",
                TelegramOutboundMessage.lease_expires_at < now,
                TelegramOutboundMessage.attempt_count >= max_attempts,
            )
            .values(
                status="failed",
                owner_token=None,
                lease_expires_at=None,
                last_error_category="attempts_exhausted",
                updated_at=func.now(),
            )
        )
        result = await self._session.execute(statement)
        return int(result.rowcount or 0)

    async def list_for_assignment(
        self,
        assignment_id: UUID,
        *,
        limit: int = 100,
    ) -> list[TelegramOutboundMessage]:
        self._ensure_rls_context()
        prefix = f"assignment:{assignment_id}:"
        statement = (
            select(TelegramOutboundMessage)
            .where(
                TelegramOutboundMessage.source_type.in_(
                    (
                        "assignment_initial",
                        "assignment_reminder",
                        "assignment_manual_reminder",
                    )
                ),
                TelegramOutboundMessage.source_key.startswith(prefix),
            )
            .order_by(TelegramOutboundMessage.created_at.desc())
            .limit(max(1, min(limit, 1000)))
        )
        return list((await self._session.scalars(statement)).all())

    async def mark_sent(
        self,
        *,
        message_id: UUID,
        owner_token: UUID,
        telegram_message_id: int,
        sent_at: datetime,
    ) -> TelegramOutboundMessage | None:
        self._ensure_rls_context()
        statement = (
            update(TelegramOutboundMessage)
            .where(
                TelegramOutboundMessage.id == message_id,
                TelegramOutboundMessage.status == "sending",
                TelegramOutboundMessage.owner_token == owner_token,
            )
            .values(
                status="sent",
                owner_token=None,
                lease_expires_at=None,
                sent_at=sent_at,
                telegram_message_id=telegram_message_id,
                last_error_category=None,
                updated_at=func.now(),
            )
            .returning(TelegramOutboundMessage)
        )
        return (await self._session.scalars(statement)).first()

    async def mark_failed(
        self,
        *,
        message_id: UUID,
        owner_token: UUID,
        retryable: bool,
        next_attempt_at: datetime,
        error_category: str,
    ) -> TelegramOutboundMessage | None:
        self._ensure_rls_context()
        statement = (
            update(TelegramOutboundMessage)
            .where(
                TelegramOutboundMessage.id == message_id,
                TelegramOutboundMessage.status == "sending",
                TelegramOutboundMessage.owner_token == owner_token,
            )
            .values(
                status="pending" if retryable else "failed",
                owner_token=None,
                lease_expires_at=None,
                next_attempt_at=next_attempt_at,
                last_error_category=error_category,
                updated_at=func.now(),
            )
            .returning(TelegramOutboundMessage)
        )
        return (await self._session.scalars(statement)).first()
