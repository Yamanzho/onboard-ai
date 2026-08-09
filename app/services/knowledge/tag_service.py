from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models.knowledge_tag import KnowledgeTag
from app.db.uow import UnitOfWork
from app.services.knowledge._slug import slugify
from app.services.tenancy import ensure_same_company


class TagService:
    """Application service for knowledge tags."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def create_tag(
        self,
        *,
        company_id: UUID,
        actor_company_id: UUID,
        name: str,
        slug: str | None = None,
    ) -> KnowledgeTag:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        try:
            resolved_slug = slug or slugify(name)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")

            existing = await uow.knowledge_tags.get_by_slug(company_id, resolved_slug)
            if existing is not None:
                raise ConflictError(
                    f"Knowledge tag slug {resolved_slug!r} already exists "
                    f"in company {company_id}"
                )

            try:
                tag = await uow.knowledge_tags.create(
                    KnowledgeTag(
                        company_id=company_id,
                        name=name,
                        slug=resolved_slug,
                    ),
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Knowledge tag slug {resolved_slug!r} already exists "
                    f"in company {company_id}"
                ) from exc
            return tag

    async def get_tag(
        self,
        tag_id: UUID,
        *,
        company_id: UUID,
    ) -> KnowledgeTag:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            tag = await uow.knowledge_tags.get_by_id(tag_id)
            if tag is None:
                raise NotFoundError(f"Knowledge tag {tag_id} not found")
            ensure_same_company(
                resource_company_id=tag.company_id,
                actor_company_id=company_id,
                not_found_message=f"Knowledge tag {tag_id} not found",
            )
            return tag

    async def list_tags(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        offset: int = 0,
        limit: int = 100,
        prefix: str | None = None,
    ) -> list[KnowledgeTag]:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            if prefix is not None:
                return await uow.knowledge_tags.search_by_prefix(
                    company_id,
                    prefix,
                    offset=offset,
                    limit=limit,
                )
            return await uow.knowledge_tags.list_by_company_id(
                company_id,
                offset=offset,
                limit=limit,
            )

    async def update_tag(
        self,
        tag_id: UUID,
        *,
        company_id: UUID,
        **values: Any,
    ) -> KnowledgeTag:
        forbidden = {"id", "company_id", "created_at"}
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(f"Cannot update fields via update_tag: {sorted(extra)}")

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            tag = await uow.knowledge_tags.get_by_id(tag_id)
            if tag is None:
                raise NotFoundError(f"Knowledge tag {tag_id} not found")
            ensure_same_company(
                resource_company_id=tag.company_id,
                actor_company_id=company_id,
                not_found_message=f"Knowledge tag {tag_id} not found",
            )

            if "slug" in values:
                new_slug = values["slug"]
                existing = await uow.knowledge_tags.get_by_slug(company_id, new_slug)
                if existing is not None and existing.id != tag_id:
                    raise ConflictError(
                        f"Knowledge tag slug {new_slug!r} already exists "
                        f"in company {company_id}"
                    )

            try:
                updated = await uow.knowledge_tags.update(tag_id, **values)
                if updated is None:
                    raise NotFoundError(f"Knowledge tag {tag_id} not found")
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Knowledge tag slug already exists in company {company_id}"
                ) from exc
            return updated
