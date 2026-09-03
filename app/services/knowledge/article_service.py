from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from app.core.exceptions import NotFoundError, ValidationError
from app.db.enums import (
    AssignmentStatus,
    CompanyAuditAction,
    EmployeeRole,
    KnowledgeArticleStatus,
    KnowledgeBodyFormat,
    KnowledgeLinkTargetType,
    KnowledgeVisibility,
)
from app.db.models.knowledge_article import KnowledgeArticle
from app.db.models.knowledge_article_link import KnowledgeArticleLink
from app.db.models.knowledge_article_version import KnowledgeArticleVersion
from app.db.models.knowledge_tag import KnowledgeTag
from app.db.uow import UnitOfWork
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.company_audit import record_company_audit
from app.services.tenancy import ensure_same_company

_ALLOWED_VISIBILITIES = {item.value for item in KnowledgeVisibility}
_ALLOWED_BODY_FORMATS = {item.value for item in KnowledgeBodyFormat}

_PUBLISHABLE_STATUSES = frozenset({KnowledgeArticleStatus.DRAFT.value})
_ARCHIVABLE_STATUSES = frozenset(
    {
        KnowledgeArticleStatus.DRAFT.value,
        KnowledgeArticleStatus.PUBLISHED.value,
    }
)
# HR/Admin manage drafts/archives; employees only get published + visibility ACL.
_KB_MANAGEMENT_ROLES = frozenset(
    {
        EmployeeRole.ADMIN.value,
        EmployeeRole.HR.value,
    }
)
_ASSIGNMENT_STATUSES_GRANTING_PROGRAM_KB = frozenset(
    {
        AssignmentStatus.PENDING.value,
        AssignmentStatus.IN_PROGRESS.value,
        AssignmentStatus.COMPLETED.value,
    }
)


class ArticleService:
    """Application service for knowledge article lifecycle and versioning."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        chunk_indexer: KnowledgeChunkIndexer | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._chunk_indexer = chunk_indexer

    async def create_article(
        self,
        *,
        company_id: UUID,
        actor_company_id: UUID,
        title: str,
        body: str,
        body_format: str = KnowledgeBodyFormat.MARKDOWN.value,
        category_id: UUID | None = None,
        visibility: str = KnowledgeVisibility.COMPANY.value,
        tag_ids: list[UUID] | None = None,
        change_summary: str | None = None,
        created_by_id: UUID | None = None,
        program_ids: list[UUID] | None = None,
    ) -> KnowledgeArticle:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        self._validate_visibility(visibility)
        self._validate_body_format(body_format)
        tag_ids = tag_ids or []

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")

            if category_id is not None:
                await self._require_category(uow, category_id, company_id)

            tags = await self._resolve_tags(uow, tag_ids, company_id)

            article = await uow.knowledge_articles.create(
                KnowledgeArticle(
                    company_id=company_id,
                    category_id=category_id,
                    status=KnowledgeArticleStatus.DRAFT.value,
                    visibility=visibility,
                    created_by_id=created_by_id,
                ),
            )
            version = await uow.knowledge_article_versions.create(
                KnowledgeArticleVersion(
                    company_id=company_id,
                    article_id=article.id,
                    version=1,
                    title=title,
                    body=body,
                    body_format=body_format,
                    change_summary=change_summary,
                    created_by_id=created_by_id,
                ),
            )
            updated = await uow.knowledge_articles.update(
                article.id,
                current_version_id=version.id,
            )
            assert updated is not None
            # Async SQLAlchemy requires the collection to be loaded before replace;
            # otherwise assignment triggers a sync lazy-load (MissingGreenlet).
            await uow.session.refresh(updated, attribute_names=["tags"])
            updated.tags = tags
            await self._replace_program_links(
                uow,
                article_id=updated.id,
                company_id=company_id,
                program_ids=program_ids or [],
            )
            await record_company_audit(
                uow,
                company_id=company_id,
                actor_employee_id=created_by_id,
                action=CompanyAuditAction.ARTICLE_CREATED.value,
                resource_type="kb_article",
                resource_id=updated.id,
                summary=f"Created article {title!r}",
                details={"status": KnowledgeArticleStatus.DRAFT.value},
            )
            await uow.session.flush()
            await uow.commit()

            loaded = await uow.knowledge_articles.get_by_id_with_relations(article.id)
            assert loaded is not None
            return loaded

    async def get_article(
        self,
        article_id: UUID,
        *,
        company_id: UUID,
        actor_role: str,
        actor_employee_id: UUID | None = None,
    ) -> KnowledgeArticle:
        """Load an article for the actor within ``company_id``.

        HR/Admin may read any same-tenant article (including draft/archived).
        Employees may only read **published** articles that pass visibility rules.
        Unauthorized access returns NotFoundError (same as missing) to avoid
        existence enumeration.
        """
        not_found = f"Knowledge article {article_id} not found"
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            article = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            if article is None:
                raise NotFoundError(not_found)
            ensure_same_company(
                resource_company_id=article.company_id,
                actor_company_id=company_id,
                not_found_message=not_found,
            )

            if actor_role in _KB_MANAGEMENT_ROLES:
                return article

            # Employee (and any other non-management role): published + visibility.
            if article.status != KnowledgeArticleStatus.PUBLISHED.value:
                raise NotFoundError(not_found)

            if article.visibility == KnowledgeVisibility.COMPANY.value:
                return article

            if article.visibility == KnowledgeVisibility.PROGRAM.value:
                if actor_employee_id is None:
                    raise NotFoundError(not_found)
                if await self._employee_may_read_program_article(
                    uow,
                    article,
                    actor_employee_id=actor_employee_id,
                ):
                    return article
                raise NotFoundError(not_found)

            # Unknown visibility value — fail closed for non-management readers.
            raise NotFoundError(not_found)

    async def _employee_may_read_program_article(
        self,
        uow: UnitOfWork,
        article: KnowledgeArticle,
        *,
        actor_employee_id: UUID,
    ) -> bool:
        """True when the employee has a non-cancelled assignment to a linked program."""
        links = list(article.links or [])
        if not links:
            return False

        assignments = await uow.assignments.list_by_employee_id(
            actor_employee_id,
            offset=0,
            limit=1000,
        )
        allowed_program_ids = {
            assignment.program_id
            for assignment in assignments
            if assignment.status in _ASSIGNMENT_STATUSES_GRANTING_PROGRAM_KB
        }
        if not allowed_program_ids:
            return False

        for link in links:
            if link.target_type == KnowledgeLinkTargetType.PROGRAM.value:
                if link.target_id in allowed_program_ids:
                    return True
                continue
            if link.target_type == KnowledgeLinkTargetType.STEP.value:
                step = await uow.steps.get_by_id(link.target_id)
                if step is not None and step.program_id in allowed_program_ids:
                    return True
        return False

    async def list_articles(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        status: str | None = None,
        category_id: UUID | None = None,
        tag_id: UUID | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = 100,
        actor_role: str | None = None,
        actor_employee_id: UUID | None = None,
    ) -> list[KnowledgeArticle]:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        is_employee_reader = (
            actor_role is not None and actor_role not in _KB_MANAGEMENT_ROLES
        )
        if is_employee_reader:
            # Employees may only enumerate published articles they are allowed to read.
            status = KnowledgeArticleStatus.PUBLISHED.value

        if status is not None:
            allowed = {item.value for item in KnowledgeArticleStatus}
            if status not in allowed:
                raise ValidationError(
                    f"Invalid article status {status!r}; allowed: {sorted(allowed)}"
                )

        search_q = None
        if q is not None:
            search_q = q.strip()
            if len(search_q) > 200:
                raise ValidationError("Search query must be at most 200 characters")
            if not search_q:
                search_q = None

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")

            articles = await uow.knowledge_articles.list_by_company_id(
                company_id,
                status=status,
                category_id=category_id,
                tag_id=tag_id,
                q=search_q,
                offset=offset,
                limit=limit,
                with_relations=True,
            )
            if is_employee_reader:
                visible: list[KnowledgeArticle] = []
                for article in articles:
                    if await self._employee_may_list_article(
                        uow,
                        article,
                        actor_employee_id=actor_employee_id,
                    ):
                        visible.append(article)
                return visible
            return articles

    async def update_article(
        self,
        article_id: UUID,
        *,
        company_id: UUID,
        created_by_id: UUID | None = None,
        **values: object,
    ) -> KnowledgeArticle:
        forbidden = {
            "id",
            "company_id",
            "created_at",
            "status",
            "current_version_id",
            "created_by_id",
        }
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(f"Cannot update fields via update_article: {sorted(extra)}")
        program_ids_provided = "program_ids" in values
        program_ids = values.pop("program_ids", None)
        if not values and not program_ids_provided:
            raise ValidationError("At least one field must be provided for update")

        visibility = values.get("visibility")
        if isinstance(visibility, str):
            self._validate_visibility(visibility)
        body_format = values.get("body_format")
        if isinstance(body_format, str):
            self._validate_body_format(body_format)

        content_keys = {"title", "body", "body_format", "change_summary"}
        content_touched = bool(content_keys.intersection(values))

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            article = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            if article is None:
                raise NotFoundError(f"Knowledge article {article_id} not found")
            ensure_same_company(
                resource_company_id=article.company_id,
                actor_company_id=company_id,
                not_found_message=f"Knowledge article {article_id} not found",
            )

            if article.status == KnowledgeArticleStatus.ARCHIVED.value:
                raise ValidationError(
                    "Cannot update an archived article; create a new article instead"
                )

            if "category_id" in values:
                category_id = values["category_id"]
                if category_id is not None:
                    if not isinstance(category_id, UUID):
                        raise ValidationError("category_id must be a UUID")
                    await self._require_category(uow, category_id, company_id)
                article.category_id = category_id  # type: ignore[assignment]

            if "visibility" in values and isinstance(values["visibility"], str):
                article.visibility = values["visibility"]

            if "tag_ids" in values:
                tag_ids = values["tag_ids"]
                if tag_ids is None:
                    article.tags = []
                elif isinstance(tag_ids, list):
                    article.tags = await self._resolve_tags(uow, tag_ids, company_id)
                else:
                    raise ValidationError("tag_ids must be a list of UUIDs")

            if program_ids_provided:
                if program_ids is None:
                    await self._replace_program_links(
                        uow,
                        article_id=article.id,
                        company_id=company_id,
                        program_ids=[],
                    )
                elif isinstance(program_ids, list):
                    await self._replace_program_links(
                        uow,
                        article_id=article.id,
                        company_id=company_id,
                        program_ids=program_ids,
                    )
                else:
                    raise ValidationError("program_ids must be a list of UUIDs")

            if content_touched:
                current = article.current_version
                if current is None:
                    raise ValidationError(
                        f"Knowledge article {article_id} has no current version"
                    )
                next_version = await uow.knowledge_article_versions.next_version_number(
                    article.id,
                )
                title = values["title"] if "title" in values else current.title
                body = values["body"] if "body" in values else current.body
                fmt = (
                    values["body_format"]
                    if "body_format" in values
                    else current.body_format
                )
                summary = (
                    values["change_summary"] if "change_summary" in values else None
                )
                version = await uow.knowledge_article_versions.create(
                    KnowledgeArticleVersion(
                        company_id=company_id,
                        article_id=article.id,
                        version=next_version,
                        title=str(title),
                        body=str(body),
                        body_format=str(fmt),
                        change_summary=str(summary) if summary is not None else None,
                        created_by_id=created_by_id,
                    ),
                )
                article.current_version_id = version.id

            await record_company_audit(
                uow,
                company_id=company_id,
                actor_employee_id=created_by_id,
                action=CompanyAuditAction.ARTICLE_UPDATED.value,
                resource_type="kb_article",
                resource_id=article.id,
                summary="Updated knowledge article",
                details={"content_changed": content_touched},
            )
            await uow.session.flush()
            await uow.commit()

            uow.session.expire(article, ["current_version", "tags", "category", "links"])
            loaded = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            assert loaded is not None
        # Draft edits are a no-op in the helper. A new current version of an
        # already-published article is indexed after this commit.
        if content_touched:
            await self._index_published_after_commit(
                loaded,
                actor_company_id=company_id,
            )
            return await self._reload_article(article_id, company_id=company_id)
        return loaded

    async def publish_article(
        self,
        article_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID | None = None,
    ) -> KnowledgeArticle:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            article = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            if article is None:
                raise NotFoundError(f"Knowledge article {article_id} not found")
            ensure_same_company(
                resource_company_id=article.company_id,
                actor_company_id=company_id,
                not_found_message=f"Knowledge article {article_id} not found",
            )

            if article.status not in _PUBLISHABLE_STATUSES:
                raise ValidationError(
                    f"Invalid status transition: cannot publish article in "
                    f"{article.status!r} status (allowed from: "
                    f"{sorted(_PUBLISHABLE_STATUSES)})"
                )
            if article.current_version is None:
                raise ValidationError(
                    f"Cannot publish article {article_id} without a current version"
                )

            article.status = KnowledgeArticleStatus.PUBLISHED.value
            if article.current_version.published_at is None:
                article.current_version.published_at = datetime.now(UTC)

            await record_company_audit(
                uow,
                company_id=company_id,
                actor_employee_id=actor_employee_id,
                action=CompanyAuditAction.ARTICLE_PUBLISHED.value,
                resource_type="kb_article",
                resource_id=article.id,
                summary="Published knowledge article",
            )
            await uow.session.flush()
            await uow.commit()

            uow.session.expire(
                article,
                ["current_version", "tags", "category", "links"],
            )
            loaded = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            assert loaded is not None
        # Post-commit derived index (separate UoW). Failure is raised so
        # callers cannot observe a silent stale vector index.
        await self._index_published_after_commit(
            loaded,
            actor_company_id=company_id,
        )
        return await self._reload_article(article_id, company_id=company_id)

    async def archive_article(
        self,
        article_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID | None = None,
    ) -> KnowledgeArticle:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            article = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            if article is None:
                raise NotFoundError(f"Knowledge article {article_id} not found")
            ensure_same_company(
                resource_company_id=article.company_id,
                actor_company_id=company_id,
                not_found_message=f"Knowledge article {article_id} not found",
            )

            if article.status not in _ARCHIVABLE_STATUSES:
                raise ValidationError(
                    f"Invalid status transition: cannot archive article in "
                    f"{article.status!r} status (allowed from: "
                    f"{sorted(_ARCHIVABLE_STATUSES)})"
                )

            article.status = KnowledgeArticleStatus.ARCHIVED.value
            await record_company_audit(
                uow,
                company_id=company_id,
                actor_employee_id=actor_employee_id,
                action=CompanyAuditAction.ARTICLE_ARCHIVED.value,
                resource_type="kb_article",
                resource_id=article.id,
                summary="Archived knowledge article",
            )
            await uow.session.flush()
            await uow.commit()

            loaded = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            assert loaded is not None
            return loaded

    async def list_versions(
        self,
        article_id: UUID,
        *,
        company_id: UUID,
        actor_role: str,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeArticleVersion]:
        await self._require_management_article(
            article_id,
            company_id=company_id,
            actor_role=actor_role,
        )
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            return await uow.knowledge_article_versions.list_by_article_id(
                article_id,
                offset=offset,
                limit=limit,
            )

    async def get_version(
        self,
        article_id: UUID,
        version: int,
        *,
        company_id: UUID,
        actor_role: str,
    ) -> KnowledgeArticleVersion:
        await self._require_management_article(
            article_id,
            company_id=company_id,
            actor_role=actor_role,
        )
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            row = await uow.knowledge_article_versions.get_by_article_and_version(
                article_id,
                version,
            )
            if row is None:
                raise NotFoundError(
                    f"Knowledge article {article_id} version {version} not found"
                )
            return row

    async def restore_version(
        self,
        article_id: UUID,
        version: int,
        *,
        company_id: UUID,
        actor_role: str,
        actor_employee_id: UUID | None = None,
    ) -> KnowledgeArticle:
        snapshot = await self.get_version(
            article_id,
            version,
            company_id=company_id,
            actor_role=actor_role,
        )
        return await self.update_article(
            article_id,
            company_id=company_id,
            created_by_id=actor_employee_id,
            title=snapshot.title,
            body=snapshot.body,
            body_format=snapshot.body_format,
            change_summary=f"Restored from version {version}",
        )

    @property
    def _indexer(self) -> KnowledgeChunkIndexer:
        if self._chunk_indexer is None:
            self._chunk_indexer = KnowledgeChunkIndexer(uow_factory=self._uow_factory)
        return self._chunk_indexer

    async def _index_published_after_commit(
        self,
        article: KnowledgeArticle,
        *,
        actor_company_id: UUID,
    ) -> None:
        """Sync pgvector after a committed KB write.

        No-op for draft/archived. Historical chunks of other versions are not
        mutated. Indexing uses the authenticated tenant, never a client-supplied
        company_id as RLS authority.
        """
        if article.status != KnowledgeArticleStatus.PUBLISHED.value:
            return
        version_id = article.current_version_id
        if version_id is None:
            return
        try:
            await self._indexer.index_published_version(
                actor_company_id=actor_company_id,
                article_id=article.id,
                version_id=version_id,
                company_id=article.company_id,
            )
        except Exception:
            # The business publication already committed. The indexer persists
            # a sanitized failed/stale state; callers receive that durable
            # health state instead of an ambiguous post-commit error.
            return

    async def _reload_article(
        self,
        article_id: UUID,
        *,
        company_id: UUID,
    ) -> KnowledgeArticle:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            article = await uow.knowledge_articles.get_by_id_with_relations(article_id)
            if article is None:
                raise NotFoundError(f"Knowledge article {article_id} not found")
            return article

    async def _require_management_article(
        self,
        article_id: UUID,
        *,
        company_id: UUID,
        actor_role: str,
    ) -> KnowledgeArticle:
        if actor_role not in _KB_MANAGEMENT_ROLES:
            raise NotFoundError(f"Knowledge article {article_id} not found")
        return await self.get_article(
            article_id,
            company_id=company_id,
            actor_role=actor_role,
        )

    async def _employee_may_list_article(
        self,
        uow: UnitOfWork,
        article: KnowledgeArticle,
        *,
        actor_employee_id: UUID | None,
    ) -> bool:
        if article.status != KnowledgeArticleStatus.PUBLISHED.value:
            return False
        if article.visibility == KnowledgeVisibility.COMPANY.value:
            return True
        if article.visibility == KnowledgeVisibility.PROGRAM.value:
            if actor_employee_id is None:
                return False
            return await self._employee_may_read_program_article(
                uow,
                article,
                actor_employee_id=actor_employee_id,
            )
        return False

    async def _replace_program_links(
        self,
        uow: UnitOfWork,
        *,
        article_id: UUID,
        company_id: UUID,
        program_ids: list[UUID],
    ) -> None:
        unique_ids = list(dict.fromkeys(program_ids))
        for program_id in unique_ids:
            if not isinstance(program_id, UUID):
                raise ValidationError("program_ids must be a list of UUIDs")
            program = await uow.onboarding_programs.get_by_id(program_id)
            if program is None:
                raise NotFoundError(f"Onboarding program {program_id} not found")
            ensure_same_company(
                resource_company_id=program.company_id,
                actor_company_id=company_id,
                not_found_message=f"Onboarding program {program_id} not found",
            )
        await uow.knowledge_article_links.delete_by_article_id_and_type(
            article_id,
            KnowledgeLinkTargetType.PROGRAM.value,
        )
        for program_id in unique_ids:
            await uow.knowledge_article_links.create(
                KnowledgeArticleLink(
                    company_id=company_id,
                    article_id=article_id,
                    target_type=KnowledgeLinkTargetType.PROGRAM.value,
                    target_id=program_id,
                ),
            )

    async def _require_category(
        self,
        uow: UnitOfWork,
        category_id: UUID,
        company_id: UUID,
    ) -> None:
        category = await uow.knowledge_categories.get_by_id(category_id)
        if category is None:
            raise NotFoundError(f"Knowledge category {category_id} not found")
        ensure_same_company(
            resource_company_id=category.company_id,
            actor_company_id=company_id,
            not_found_message=f"Knowledge category {category_id} not found",
        )

    async def _resolve_tags(
        self,
        uow: UnitOfWork,
        tag_ids: list[UUID],
        company_id: UUID,
    ) -> list[KnowledgeTag]:
        if not tag_ids:
            return []

        unique_ids = list(dict.fromkeys(tag_ids))
        tags: list[KnowledgeTag] = []
        for tag_id in unique_ids:
            tag = await uow.knowledge_tags.get_by_id(tag_id)
            if tag is None:
                raise NotFoundError(f"Knowledge tag {tag_id} not found")
            ensure_same_company(
                resource_company_id=tag.company_id,
                actor_company_id=company_id,
                not_found_message=f"Knowledge tag {tag_id} not found",
            )
            tags.append(tag)
        return tags

    @staticmethod
    def _validate_visibility(visibility: str) -> None:
        if visibility not in _ALLOWED_VISIBILITIES:
            raise ValidationError(
                f"Invalid visibility {visibility!r}; "
                f"allowed: {sorted(_ALLOWED_VISIBILITIES)}"
            )

    @staticmethod
    def _validate_body_format(body_format: str) -> None:
        if body_format not in _ALLOWED_BODY_FORMATS:
            raise ValidationError(
                f"Invalid body_format {body_format!r}; "
                f"allowed: {sorted(_ALLOWED_BODY_FORMATS)}"
            )
