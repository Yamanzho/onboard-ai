from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.progress import Progress
from app.repositories.base import BaseRepository, _MAX_LIST_LIMIT


class ProgressRepository(BaseRepository[Progress]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Progress)

    async def list_by_assignment_id(
        self,
        assignment_id: UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[Progress]:
        stmt = self._assignment_list_statement(
            assignment_id,
            offset=offset,
            limit=limit,
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_by_assignment_and_step(
        self,
        assignment_id: UUID,
        step_id: UUID,
    ) -> Progress | None:
        stmt = select(Progress).where(
            Progress.assignment_id == assignment_id,
            Progress.step_id == step_id,
        )
        return await self._session.scalar(stmt)

    def _assignment_list_statement(
        self,
        assignment_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> Select[tuple[Progress]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        return (
            select(Progress)
            .where(Progress.assignment_id == assignment_id)
            .order_by(Progress.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
