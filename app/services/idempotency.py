from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from app.core.config import get_settings
from app.core.exceptions import ConflictError, ValidationError
from app.core.metrics import IDEMPOTENCY_CLAIMS, IDEMPOTENCY_TRANSITIONS
from app.core.request_id import request_id_log_value
from app.db.uow import UnitOfWork

logger = logging.getLogger("app.idempotency")

TELEGRAM_SCOPE = "telegram-bot"
TELEGRAM_OPERATION = "telegram-update"
AI_OPERATION = "ai-chat"
TELEGRAM_LEASE_SECONDS = 300
_KEY_RE = re.compile(r"^[A-Za-z0-9:_-]{8,128}$")
_UPDATE_TYPE_RE = re.compile(r"^[a-z_]{1,32}$")
ClaimState = Literal["acquired", "completed", "processing"]


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    state: ClaimState
    receipt_id: UUID
    owner_token: UUID | None
    response: dict[str, Any] | None = None

    @property
    def acquired(self) -> bool:
        return self.state == "acquired"


class IdempotencyService:
    """Own durable claim transitions; callers own application work."""

    async def claim_telegram_update(
        self,
        *,
        update_id: int,
        update_type: str,
    ) -> IdempotencyClaim:
        if not isinstance(update_id, int) or isinstance(update_id, bool) or update_id < 0:
            raise ValidationError("Telegram update id must be a non-negative integer")
        normalized_type = update_type.strip().lower()
        if not _UPDATE_TYPE_RE.fullmatch(normalized_type):
            raise ValidationError("Telegram update type is invalid")
        key = str(update_id)
        claim = await self._claim(
            scope=TELEGRAM_SCOPE,
            operation=TELEGRAM_OPERATION,
            idempotency_key=key,
            request_hash=None,
            company_id=None,
            employee_id=None,
            lease_seconds=TELEGRAM_LEASE_SECONDS,
            platform=True,
        )
        logger.info(
            "idempotency request_id=%s operation=telegram_update update_id=%s "
            "update_type=%s outcome=%s",
            request_id_log_value(),
            update_id,
            normalized_type,
            "accepted" if claim.acquired else f"duplicate_{claim.state}",
        )
        return claim

    async def complete_telegram_update(
        self,
        *,
        receipt_id: UUID,
        owner_token: UUID,
    ) -> bool:
        async with UnitOfWork() as uow:
            await uow.enter_platform()
            completed = await uow.idempotency_receipts.complete(
                receipt_id=receipt_id,
                owner_token=owner_token,
                completed_at=datetime.now(UTC),
            )
            await uow.commit()
        logger.info(
            "idempotency request_id=%s operation=telegram_update outcome=%s",
            request_id_log_value(),
            "completed" if completed is not None else "ownership_lost",
        )
        IDEMPOTENCY_TRANSITIONS.labels(
            operation=TELEGRAM_OPERATION,
            outcome="completed" if completed is not None else "ownership_lost",
        ).inc()
        return completed is not None

    async def fail_telegram_update(
        self,
        *,
        receipt_id: UUID,
        owner_token: UUID,
    ) -> bool:
        return await self._fail(
            receipt_id=receipt_id,
            owner_token=owner_token,
            company_id=None,
            employee_id=None,
            platform=True,
            operation=TELEGRAM_OPERATION,
        )

    async def claim_ai_turn(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        idempotency_key: str,
        request_hash: str,
    ) -> IdempotencyClaim:
        key = validate_idempotency_key(idempotency_key)
        claim = await self._claim(
            scope=f"employee:{actor_employee_id}",
            operation=AI_OPERATION,
            idempotency_key=key,
            request_hash=request_hash,
            company_id=actor_company_id,
            employee_id=actor_employee_id,
            lease_seconds=max(
                120,
                get_settings().ai_chat_timeout_seconds + 30,
            ),
            platform=False,
        )
        logger.info(
            "idempotency request_id=%s operation=ai_chat company_id=%s "
            "employee_id=%s outcome=%s",
            request_id_log_value(),
            actor_company_id,
            actor_employee_id,
            "accepted" if claim.acquired else f"duplicate_{claim.state}",
        )
        return claim

    async def fail_ai_turn(
        self,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        receipt_id: UUID,
        owner_token: UUID,
    ) -> bool:
        return await self._fail(
            receipt_id=receipt_id,
            owner_token=owner_token,
            company_id=actor_company_id,
            employee_id=actor_employee_id,
            platform=False,
            operation=AI_OPERATION,
        )

    async def _claim(
        self,
        *,
        scope: str,
        operation: str,
        idempotency_key: str,
        request_hash: str | None,
        company_id: UUID | None,
        employee_id: UUID | None,
        lease_seconds: int,
        platform: bool,
    ) -> IdempotencyClaim:
        owner_token = uuid4()
        receipt_id = uuid4()
        async with UnitOfWork() as uow:
            if platform:
                await uow.enter_platform()
            else:
                assert company_id is not None
                await uow.enter_tenant(company_id)
            result = await uow.idempotency_receipts.claim(
                receipt_id=receipt_id,
                scope=scope,
                operation=operation,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                owner_token=owner_token,
                lease_expires_at=datetime.now(UTC)
                + timedelta(seconds=lease_seconds),
                company_id=company_id,
                employee_id=employee_id,
            )
            if result.receipt.request_hash != request_hash:
                IDEMPOTENCY_CLAIMS.labels(
                    operation=operation,
                    outcome="hash_conflict",
                ).inc()
                raise ConflictError(
                    "Idempotency key was already used for a different request"
                )
            await uow.commit()

        outcome = (
            "acquired"
            if result.state == "acquired"
            else f"duplicate_{result.state}"
        )
        IDEMPOTENCY_CLAIMS.labels(operation=operation, outcome=outcome).inc()
        if result.state == "acquired":
            return IdempotencyClaim(
                state="acquired",
                receipt_id=result.receipt.id,
                owner_token=owner_token,
            )
        response = (
            dict(result.receipt.response)
            if isinstance(result.receipt.response, dict)
            else None
        )
        return IdempotencyClaim(
            state=result.state,
            receipt_id=result.receipt.id,
            owner_token=None,
            response=response,
        )

    async def _fail(
        self,
        *,
        receipt_id: UUID,
        owner_token: UUID,
        company_id: UUID | None,
        employee_id: UUID | None,
        platform: bool,
        operation: str,
    ) -> bool:
        async with UnitOfWork() as uow:
            if platform:
                await uow.enter_platform()
            else:
                assert company_id is not None and employee_id is not None
                await uow.enter_tenant(company_id)
            failed = await uow.idempotency_receipts.fail(
                receipt_id=receipt_id,
                owner_token=owner_token,
            )
            await uow.commit()
        logger.warning(
            "idempotency request_id=%s operation=%s company_id=%s "
            "employee_id=%s outcome=%s",
            request_id_log_value(),
            operation,
            company_id or "",
            employee_id or "",
            "failed_retryable" if failed is not None else "ownership_lost",
        )
        IDEMPOTENCY_TRANSITIONS.labels(
            operation=operation,
            outcome="failed" if failed is not None else "ownership_lost",
        ).inc()
        return failed is not None


def validate_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not _KEY_RE.fullmatch(normalized):
        raise ValidationError(
            "Idempotency-Key must be 8-128 characters using letters, digits, ':', '_', or '-'"
        )
    return normalized


def hash_ai_request(*, message: str, conversation_id: UUID | None) -> str:
    canonical = json.dumps(
        {
            "message": message.strip(),
            "conversation_id": str(conversation_id) if conversation_id else None,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
