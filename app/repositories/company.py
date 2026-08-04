from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import Company
from app.repositories.base import BaseRepository


class CompanyRepository(BaseRepository[Company]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Company)
