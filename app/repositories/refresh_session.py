from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.refresh_session import RefreshSession
from app.repositories.base import BaseRepository


class RefreshSessionRepository(BaseRepository[RefreshSession]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, RefreshSession)

    async def get_by_token_hash_for_update(self, token_hash: str) -> RefreshSession | None:
        self._ensure_rls_context()
        stmt = (
            select(RefreshSession)
            .where(RefreshSession.token_hash == token_hash)
            .with_for_update()
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def revoke_family(self, family_id: UUID) -> int:
        self._ensure_rls_context()
        stmt = (
            update(RefreshSession)
            .where(
                RefreshSession.family_id == family_id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)

    async def revoke_by_token_hash(self, token_hash: str) -> int:
        self._ensure_rls_context()
        stmt = (
            update(RefreshSession)
            .where(
                RefreshSession.token_hash == token_hash,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)

    async def revoke_all_for_subject(self, *, subject_type: str, subject_id: UUID) -> int:
        self._ensure_rls_context()
        stmt = (
            update(RefreshSession)
            .where(
                RefreshSession.subject_type == subject_type,
                RefreshSession.subject_id == subject_id,
                RefreshSession.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)
