from uuid import UUID

from sqlalchemy import Select, cast, exists, func, literal, or_, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.knowledge_article import KnowledgeArticle
from app.db.models.knowledge_article_link import KnowledgeArticleLink
from app.db.models.knowledge_article_tag import KnowledgeArticleTag
from app.db.models.knowledge_article_version import KnowledgeArticleVersion
from app.db.models.knowledge_category import KnowledgeCategory
from app.db.models.knowledge_tag import KnowledgeTag
from app.repositories.base import _MAX_LIST_LIMIT, BaseRepository

_MAX_SEARCH_Q = 200


class KnowledgeArticleRepository(BaseRepository[KnowledgeArticle]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, KnowledgeArticle)

    async def get_by_id_with_relations(self, article_id: UUID) -> KnowledgeArticle | None:
        self._ensure_rls_context()
        stmt = (
            select(KnowledgeArticle)
            .where(KnowledgeArticle.id == article_id)
            .options(
                selectinload(KnowledgeArticle.current_version),
                selectinload(KnowledgeArticle.tags),
                selectinload(KnowledgeArticle.links),
                selectinload(KnowledgeArticle.category),
            )
        )
        result = await self._session.scalars(stmt)
        return result.first()

    async def list_by_company_id(
        self,
        company_id: UUID,
        *,
        status: str | None = None,
        category_id: UUID | None = None,
        tag_id: UUID | None = None,
        q: str | None = None,
        target_type: str | None = None,
        target_id: UUID | None = None,
        offset: int = 0,
        limit: int = 100,
        with_relations: bool = False,
    ) -> list[KnowledgeArticle]:
        self._ensure_rls_context()
        stmt = self._company_list_statement(
            company_id,
            status=status,
            category_id=category_id,
            tag_id=tag_id,
            q=q,
            target_type=target_type,
            target_id=target_id,
            offset=offset,
            limit=limit,
        )
        if with_relations:
            stmt = stmt.options(
                selectinload(KnowledgeArticle.current_version),
                selectinload(KnowledgeArticle.tags),
                selectinload(KnowledgeArticle.links),
                selectinload(KnowledgeArticle.category),
            )
        result = await self._session.scalars(stmt)
        return list(result.unique().all())

    def _company_list_statement(
        self,
        company_id: UUID,
        *,
        status: str | None,
        category_id: UUID | None,
        tag_id: UUID | None,
        q: str | None,
        target_type: str | None,
        target_id: UUID | None,
        offset: int,
        limit: int,
    ) -> Select[tuple[KnowledgeArticle]]:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {_MAX_LIST_LIMIT}")
        if (target_type is None) ^ (target_id is None):
            raise ValueError("target_type and target_id must be provided together")

        stmt: Select[tuple[KnowledgeArticle]] = select(KnowledgeArticle).where(
            KnowledgeArticle.company_id == company_id,
        )
        if status is not None:
            stmt = stmt.where(KnowledgeArticle.status == status)
        if category_id is not None:
            stmt = stmt.where(KnowledgeArticle.category_id == category_id)
        if tag_id is not None:
            stmt = stmt.join(
                KnowledgeArticleTag,
                KnowledgeArticleTag.article_id == KnowledgeArticle.id,
            ).where(KnowledgeArticleTag.tag_id == tag_id)
        if target_type is not None and target_id is not None:
            stmt = stmt.join(
                KnowledgeArticleLink,
                KnowledgeArticleLink.article_id == KnowledgeArticle.id,
            ).where(
                KnowledgeArticleLink.target_type == target_type,
                KnowledgeArticleLink.target_id == target_id,
            )
        if q:
            stmt = self._apply_search(stmt, q)

        return (
            stmt.order_by(KnowledgeArticle.created_at.desc())
            .offset(offset)
            .limit(limit)
        )

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _apply_search(
        self,
        stmt: Select[tuple[KnowledgeArticle]],
        q: str,
    ) -> Select[tuple[KnowledgeArticle]]:
        needle = q.strip()[:_MAX_SEARCH_Q]
        if not needle:
            return stmt
        pattern = f"%{self._escape_like(needle)}%"
        # PostgreSQL to_tsvector/plainto_tsquery require regconfig, not varchar.
        config = cast(literal("simple"), REGCONFIG)
        search_vector = func.to_tsvector(
            config,
            func.concat(
                func.coalesce(KnowledgeArticleVersion.title, ""),
                literal(" "),
                func.coalesce(KnowledgeArticleVersion.body, ""),
            ),
        )
        tsquery = func.plainto_tsquery(config, needle)
        tag_match = exists(
            select(1)
            .select_from(KnowledgeArticleTag)
            .join(KnowledgeTag, KnowledgeTag.id == KnowledgeArticleTag.tag_id)
            .where(
                KnowledgeArticleTag.article_id == KnowledgeArticle.id,
                KnowledgeTag.name.ilike(pattern, escape="\\"),
            )
        )
        return (
            stmt.join(
                KnowledgeArticleVersion,
                KnowledgeArticle.current_version_id == KnowledgeArticleVersion.id,
            )
            .outerjoin(
                KnowledgeCategory,
                KnowledgeArticle.category_id == KnowledgeCategory.id,
            )
            .where(
                or_(
                    search_vector.op("@@")(tsquery),
                    KnowledgeArticleVersion.title.ilike(pattern, escape="\\"),
                    KnowledgeArticleVersion.body.ilike(pattern, escape="\\"),
                    KnowledgeCategory.name.ilike(pattern, escape="\\"),
                    tag_match,
                )
            )
        )
