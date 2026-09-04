from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assignment_reminder_preference import AssignmentReminderPreference
from app.repositories.base import BaseRepository


class AssignmentReminderPreferenceRepository(BaseRepository[AssignmentReminderPreference]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, AssignmentReminderPreference)

    async def get_by_assignment_id(
        self,
        assignment_id: UUID,
    ) -> AssignmentReminderPreference | None:
        self._ensure_rls_context()
        statement = select(AssignmentReminderPreference).where(
            AssignmentReminderPreference.assignment_id == assignment_id,
        )
        return (await self._session.scalars(statement)).first()
