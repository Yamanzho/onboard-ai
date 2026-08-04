from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.onboarding_program import OnboardingProgram
from app.repositories.base import BaseRepository, _MAX_LIST_LIMIT


class OnboardingProgramRepository(BaseRepository[OnboardingProgram]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, OnboardingProgram)

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        is_active: bool | None = None,
    ) -> list[OnboardingProgram]:
        stmt = self._company_list_statement(
            company_id,
            offset=offset,
            limit=limit,
            is_active=is_active,
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    def _company_list_statement(
        self,
        company_id: UUID,
        *,
        offset: int,
        limit: int,
        is_active: bool | None,
    ) -> Select[tuple[OnboardingProgram]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt: Select[tuple[OnboardingProgram]] = select(OnboardingProgram).where(
            OnboardingProgram.company_id == company_id,
        )
        if is_active is not None:
            stmt = stmt.where(OnboardingProgram.is_active.is_(is_active))
        return stmt.order_by(OnboardingProgram.created_at.desc()).offset(offset).limit(limit)
