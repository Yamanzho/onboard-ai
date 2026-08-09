from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.models.knowledge_category import KnowledgeCategory
from app.db.uow import UnitOfWork
from app.services.knowledge._slug import slugify
from app.services.tenancy import ensure_same_company


class CategoryService:
    """Application service for knowledge category taxonomy."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def create_category(
        self,
        *,
        company_id: UUID,
        actor_company_id: UUID,
        name: str,
        slug: str | None = None,
        parent_id: UUID | None = None,
        position: int = 0,
    ) -> KnowledgeCategory:
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

            if parent_id is not None:
                parent = await uow.knowledge_categories.get_by_id(parent_id)
                if parent is None:
                    raise NotFoundError(f"Knowledge category {parent_id} not found")
                ensure_same_company(
                    resource_company_id=parent.company_id,
                    actor_company_id=company_id,
                    not_found_message=f"Knowledge category {parent_id} not found",
                )

            try:
                category = await uow.knowledge_categories.create(
                    KnowledgeCategory(
                        company_id=company_id,
                        parent_id=parent_id,
                        name=name,
                        slug=resolved_slug,
                        position=position,
                    ),
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Knowledge category slug {resolved_slug!r} already exists "
                    f"in company {company_id}"
                ) from exc
            return category

    async def get_category(
        self,
        category_id: UUID,
        *,
        company_id: UUID,
    ) -> KnowledgeCategory:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            category = await uow.knowledge_categories.get_by_id(category_id)
            if category is None:
                raise NotFoundError(f"Knowledge category {category_id} not found")
            ensure_same_company(
                resource_company_id=category.company_id,
                actor_company_id=company_id,
                not_found_message=f"Knowledge category {category_id} not found",
            )
            return category

    async def list_categories(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        parent_id: UUID | None = None,
        roots_only: bool = False,
        offset: int = 0,
        limit: int = 100,
    ) -> list[KnowledgeCategory]:
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
            return await uow.knowledge_categories.list_by_company_id(
                company_id,
                parent_id=parent_id,
                roots_only=roots_only,
                offset=offset,
                limit=limit,
            )

    async def update_category(
        self,
        category_id: UUID,
        *,
        company_id: UUID,
        **values: Any,
    ) -> KnowledgeCategory:
        forbidden = {"id", "company_id", "created_at"}
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(f"Cannot update fields via update_category: {sorted(extra)}")

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            category = await uow.knowledge_categories.get_by_id(category_id)
            if category is None:
                raise NotFoundError(f"Knowledge category {category_id} not found")
            ensure_same_company(
                resource_company_id=category.company_id,
                actor_company_id=company_id,
                not_found_message=f"Knowledge category {category_id} not found",
            )

            if "parent_id" in values and values["parent_id"] is not None:
                parent_id = values["parent_id"]
                if parent_id == category_id:
                    raise ValidationError("Category cannot be its own parent")
                parent = await uow.knowledge_categories.get_by_id(parent_id)
                if parent is None:
                    raise NotFoundError(f"Knowledge category {parent_id} not found")
                ensure_same_company(
                    resource_company_id=parent.company_id,
                    actor_company_id=company_id,
                    not_found_message=f"Knowledge category {parent_id} not found",
                )

            try:
                updated = await uow.knowledge_categories.update(category_id, **values)
                if updated is None:
                    raise NotFoundError(f"Knowledge category {category_id} not found")
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Knowledge category slug already exists in company {company_id}"
                ) from exc
            return updated
