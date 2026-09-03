from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.idempotency_receipt import IdempotencyReceipt
from app.repositories.base import BaseRepository

PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"

ClaimState = Literal["acquired", "completed", "processing"]


@dataclass(frozen=True, slots=True)
class ReceiptClaim:
    state: ClaimState
    receipt: IdempotencyReceipt


class IdempotencyReceiptRepository(BaseRepository[IdempotencyReceipt]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, IdempotencyReceipt)

    async def claim(
        self,
        *,
        receipt_id: UUID,
        scope: str,
        operation: str,
        idempotency_key: str,
        request_hash: str | None,
        owner_token: UUID,
        lease_expires_at: datetime,
        company_id: UUID | None,
        employee_id: UUID | None,
    ) -> ReceiptClaim:
        """Atomically insert or reclaim a failed/stale receipt."""
        self._ensure_rls_context()
        table = IdempotencyReceipt
        statement = insert(table).values(
            id=receipt_id,
            scope=scope,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            status=PROCESSING,
            owner_token=owner_token,
            company_id=company_id,
            employee_id=employee_id,
            response=None,
            lease_expires_at=lease_expires_at,
            completed_at=None,
        )
        excluded = statement.excluded
        same_request = table.request_hash.is_not_distinct_from(excluded.request_hash)
        reclaimable = or_(
            table.status == FAILED,
            and_(
                table.status == PROCESSING,
                table.lease_expires_at < func.now(),
            ),
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_idempotency_receipts_scope_operation_key",
            set_={
                "status": PROCESSING,
                "owner_token": owner_token,
                "lease_expires_at": lease_expires_at,
                "completed_at": None,
                "response": None,
                "updated_at": func.now(),
            },
            where=and_(same_request, reclaimable),
        ).returning(table)
        claimed = (await self._session.scalars(statement)).first()
        if claimed is not None:
            return ReceiptClaim(state="acquired", receipt=claimed)

        existing = await self.get_scoped(
            scope=scope,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        if existing is None:
            raise RuntimeError("Idempotency receipt conflict was not visible")
        state: ClaimState = (
            "completed" if existing.status == COMPLETED else "processing"
        )
        return ReceiptClaim(state=state, receipt=existing)

    async def get_scoped(
        self,
        *,
        scope: str,
        operation: str,
        idempotency_key: str,
    ) -> IdempotencyReceipt | None:
        self._ensure_rls_context()
        statement = select(IdempotencyReceipt).where(
            IdempotencyReceipt.scope == scope,
            IdempotencyReceipt.operation == operation,
            IdempotencyReceipt.idempotency_key == idempotency_key,
        )
        return (await self._session.scalars(statement)).first()

    async def complete(
        self,
        *,
        receipt_id: UUID,
        owner_token: UUID,
        completed_at: datetime,
        response: dict[str, Any] | None = None,
        company_id: UUID | None = None,
        employee_id: UUID | None = None,
    ) -> IdempotencyReceipt | None:
        self._ensure_rls_context()
        values: dict[str, Any] = {
            "status": COMPLETED,
            "owner_token": None,
            "lease_expires_at": None,
            "completed_at": completed_at,
            "response": response,
            "updated_at": func.now(),
        }
        if company_id is not None and employee_id is not None:
            values["company_id"] = company_id
            values["employee_id"] = employee_id
        statement = (
            update(IdempotencyReceipt)
            .where(
                IdempotencyReceipt.id == receipt_id,
                IdempotencyReceipt.status == PROCESSING,
                IdempotencyReceipt.owner_token == owner_token,
            )
            .values(**values)
            .returning(IdempotencyReceipt)
        )
        return (await self._session.scalars(statement)).first()

    async def fail(
        self,
        *,
        receipt_id: UUID,
        owner_token: UUID,
    ) -> IdempotencyReceipt | None:
        self._ensure_rls_context()
        statement = (
            update(IdempotencyReceipt)
            .where(
                IdempotencyReceipt.id == receipt_id,
                IdempotencyReceipt.status == PROCESSING,
                IdempotencyReceipt.owner_token == owner_token,
            )
            .values(
                status=FAILED,
                owner_token=None,
                lease_expires_at=None,
                updated_at=func.now(),
            )
            .returning(IdempotencyReceipt)
        )
        return (await self._session.scalars(statement)).first()
