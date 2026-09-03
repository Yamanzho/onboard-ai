from datetime import timedelta
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import KnowledgeIndexStatus
from app.db.models.knowledge_article_version import KnowledgeArticleVersion
from app.repositories.base import _MAX_LIST_LIMIT, BaseRepository


class KnowledgeArticleVersionRepository(BaseRepository[KnowledgeArticleVersion]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, KnowledgeArticleVersion)

    async def list_by_article_id(
        self,
        article_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeArticleVersion]:
        self._ensure_rls_context()
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")

        stmt = (
            select(KnowledgeArticleVersion)
            .where(KnowledgeArticleVersion.article_id == article_id)
            .order_by(KnowledgeArticleVersion.version.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.scalars(stmt)
        return list(result.all())

    async def get_by_article_and_version(
        self,
        article_id: UUID,
        version: int,
    ) -> KnowledgeArticleVersion | None:
        self._ensure_rls_context()
        stmt = select(KnowledgeArticleVersion).where(
            KnowledgeArticleVersion.article_id == article_id,
            KnowledgeArticleVersion.version == version,
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def next_version_number(self, article_id: UUID) -> int:
        self._ensure_rls_context()
        stmt = select(func.coalesce(func.max(KnowledgeArticleVersion.version), 0)).where(
            KnowledgeArticleVersion.article_id == article_id,
        )
        current = await self._session.scalar(stmt)
        return int(current or 0) + 1

    async def claim_indexing(
        self,
        version_id: UUID,
        *,
        owner_token: UUID,
        lease_seconds: int,
    ) -> KnowledgeArticleVersion | None:
        """Atomically claim a version unless another live DB lease owns it."""
        self._ensure_rls_context()
        stmt = (
            update(KnowledgeArticleVersion)
            .where(KnowledgeArticleVersion.id == version_id)
            .where(
                (KnowledgeArticleVersion.indexing_owner_token.is_(None))
                | (KnowledgeArticleVersion.indexing_lease_expires_at <= func.now())
            )
            .values(
                index_status=case(
                    (
                        KnowledgeArticleVersion.index_status == KnowledgeIndexStatus.INDEXED.value,
                        KnowledgeIndexStatus.INDEXED.value,
                    ),
                    else_=KnowledgeIndexStatus.INDEXING.value,
                ),
                indexing_started_at=func.now(),
                indexing_owner_token=owner_token,
                indexing_lease_expires_at=func.now() + timedelta(seconds=lease_seconds),
            )
            .returning(KnowledgeArticleVersion)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def renew_indexing_lease(
        self,
        version_id: UUID,
        *,
        owner_token: UUID,
        lease_seconds: int,
    ) -> bool:
        self._ensure_rls_context()
        result = await self._session.execute(
            update(KnowledgeArticleVersion)
            .where(KnowledgeArticleVersion.id == version_id)
            .where(KnowledgeArticleVersion.indexing_owner_token == owner_token)
            .where(KnowledgeArticleVersion.indexing_lease_expires_at > func.now())
            .values(indexing_lease_expires_at=func.now() + timedelta(seconds=lease_seconds))
        )
        return bool(result.rowcount)

    async def get_claim_for_update(
        self,
        version_id: UUID,
        *,
        owner_token: UUID,
    ) -> KnowledgeArticleVersion | None:
        self._ensure_rls_context()
        result = await self._session.scalars(
            select(KnowledgeArticleVersion)
            .where(KnowledgeArticleVersion.id == version_id)
            .where(KnowledgeArticleVersion.indexing_owner_token == owner_token)
            .where(KnowledgeArticleVersion.indexing_lease_expires_at > func.now())
            .with_for_update()
        )
        return result.first()

    async def get_by_id_for_update(
        self,
        version_id: UUID,
    ) -> KnowledgeArticleVersion | None:
        self._ensure_rls_context()
        result = await self._session.scalars(
            select(KnowledgeArticleVersion)
            .where(KnowledgeArticleVersion.id == version_id)
            .with_for_update()
        )
        return result.first()
