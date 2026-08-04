from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.company import Company
from app.db.uow import UnitOfWork
from app.services.tenancy import ensure_same_company


class CompanyService:
    """Application service for Company use cases (UnitOfWork + repositories)."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def create_company(
        self,
        *,
        name: str,
        slug: str,
        timezone: str = "UTC",
        settings: dict[str, Any] | None = None,
    ) -> Company:
        async with self._uow_factory() as uow:
            try:
                company = await uow.companies.create(
                    Company(
                        name=name,
                        slug=slug,
                        timezone=timezone,
                        settings=settings if settings is not None else {},
                    ),
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError("Company with this slug already exists") from exc
            return company

    async def get_company(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
    ) -> Company:
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            ensure_same_company(
                resource_company_id=company.id,
                actor_company_id=actor_company_id,
                not_found_message=f"Company {company_id} not found",
            )
            return company

    async def list_companies(
        self,
        *,
        actor_company_id: UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Company]:
        """Return only the caller's own company (tenant-scoped)."""
        if offset > 0:
            return []
        company = await self.get_company(actor_company_id, actor_company_id=actor_company_id)
        return [company][:limit]

    async def update_company(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        **values: Any,
    ) -> Company:
        if not values:
            return await self.get_company(company_id, actor_company_id=actor_company_id)

        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            ensure_same_company(
                resource_company_id=company.id,
                actor_company_id=actor_company_id,
                not_found_message=f"Company {company_id} not found",
            )
            try:
                updated = await uow.companies.update(company_id, **values)
                if updated is None:
                    raise NotFoundError(f"Company {company_id} not found")
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError("Company with this slug already exists") from exc
            return updated

    async def delete_company(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
    ) -> None:
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            ensure_same_company(
                resource_company_id=company.id,
                actor_company_id=actor_company_id,
                not_found_message=f"Company {company_id} not found",
            )
            deleted = await uow.companies.delete(company_id)
            if not deleted:
                raise NotFoundError(f"Company {company_id} not found")
            await uow.commit()

    async def rename_company(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        name: str,
    ) -> Company:
        return await self.update_company(
            company_id,
            actor_company_id=actor_company_id,
            name=name,
        )

    async def deactivate_company(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
    ) -> Company:
        return await self.update_company(
            company_id,
            actor_company_id=actor_company_id,
            is_active=False,
        )
