from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError
from app.db.enums import CompanyAuditAction
from app.db.models.company import Company
from app.db.uow import UnitOfWork
from app.services.company_audit import record_company_audit
from app.services.notification_settings import merge_company_settings
from app.services.tenancy import ensure_same_company

_PLATFORM_LIFECYCLE_DETAIL = (
    "Only platform Super Admin can manage tenant lifecycle. "
    "Use /api/v1/super-admin/companies."
)

# Fields that change tenant lifecycle / billing boundary — not editable by tenants.
_PLATFORM_ONLY_UPDATE_FIELDS = frozenset({"is_active"})


class CompanyService:
    """Tenant-scoped Company use cases (own company read/update only).

    Creating, deleting, and activating/deactivating tenants are platform
    operations owned by ``PlatformService`` under Super Admin auth.
    """

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
        """Rejected: tenant provisioning is platform-only.

        Callers must use ``PlatformService.create_company_with_admin``.
        """
        del name, slug, timezone, settings
        raise ForbiddenError(_PLATFORM_LIFECYCLE_DETAIL)

    async def get_company(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
    ) -> Company:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(actor_company_id)
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
        actor_employee_id: UUID | None = None,
        **values: Any,
    ) -> Company:
        forbidden = _PLATFORM_ONLY_UPDATE_FIELDS.intersection(values)
        if forbidden:
            raise ForbiddenError(
                "Company activation is a platform operation. "
                "Use /api/v1/super-admin/companies/{id}/activate|deactivate."
            )

        if not values:
            return await self.get_company(company_id, actor_company_id=actor_company_id)

        async with self._uow_factory() as uow:
            await uow.enter_tenant(actor_company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            ensure_same_company(
                resource_company_id=company.id,
                actor_company_id=actor_company_id,
                not_found_message=f"Company {company_id} not found",
            )
            if "settings" in values and isinstance(values["settings"], dict):
                values["settings"] = merge_company_settings(
                    company.settings,
                    values["settings"],
                )
            try:
                updated = await uow.companies.update(company_id, **values)
                if updated is None:
                    raise NotFoundError(f"Company {company_id} not found")
                if "settings" in values or "timezone" in values:
                    await record_company_audit(
                        uow,
                        company_id=company_id,
                        actor_employee_id=actor_employee_id,
                        action=CompanyAuditAction.COMPANY_SETTINGS_CHANGED.value,
                        resource_type="company",
                        resource_id=company_id,
                        summary="Updated company notification settings",
                        details={
                            "timezone": updated.timezone,
                            "notifications": (updated.settings or {}).get(
                                "notifications"
                            ),
                        },
                    )
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
        """Rejected: hard delete is platform-only (prefer Super Admin deactivate)."""
        del company_id, actor_company_id
        raise ForbiddenError(_PLATFORM_LIFECYCLE_DETAIL)

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
        """Rejected: activation lifecycle is platform-only."""
        del company_id, actor_company_id
        raise ForbiddenError(
            "Company activation is a platform operation. "
            "Use /api/v1/super-admin/companies/{id}/activate|deactivate."
        )
