from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.step import Step
from app.repositories.base import BaseRepository, _MAX_LIST_LIMIT


class StepRepository(BaseRepository[Step]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Step)

    async def list_by_program_id(
        self,
        program_id: UUID,
        *,
        offset: int = 0,
        limit: int = 1000,
    ) -> list[Step]:
        self._ensure_rls_context()
        stmt = self._program_list_statement(program_id, offset=offset, limit=limit)
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_max_position(self, program_id: UUID) -> int | None:
        self._ensure_rls_context()
        stmt = select(func.max(Step.position)).where(Step.program_id == program_id)
        result = await self._session.scalar(stmt)
        return result

    def _program_list_statement(
        self,
        program_id: UUID,
        *,
        offset: int,
        limit: int,
    ) -> Select[tuple[Step]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        return (
            select(Step)
            .where(Step.program_id == program_id)
            .order_by(Step.position.asc())
            .offset(offset)
            .limit(limit)
        )
