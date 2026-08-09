"""Tenant isolation helpers for the service layer."""

from uuid import UUID

from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.models.company import Company


def ensure_same_company(
    *,
    resource_company_id: UUID,
    actor_company_id: UUID,
    not_found_message: str,
) -> None:
    """Raise NotFoundError when the resource belongs to another tenant.

    Uses 404 (not 403) so callers cannot probe whether a foreign UUID exists.
    """
    if resource_company_id != actor_company_id:
        raise NotFoundError(not_found_message)


def ensure_company_is_active(company: Company | None, *, company_id: UUID) -> Company:
    """Raise ForbiddenError when the tenant is missing or deactivated."""
    if company is None:
        raise ForbiddenError(f"Company {company_id} is deactivated")
    if not company.is_active:
        raise ForbiddenError("Company is deactivated")
    return company
