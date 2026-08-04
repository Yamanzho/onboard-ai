"""Tenant isolation helpers for the service layer."""

from uuid import UUID

from app.core.exceptions import NotFoundError


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
