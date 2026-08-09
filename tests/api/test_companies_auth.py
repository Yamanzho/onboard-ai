"""Authorization tests for company (tenant) lifecycle operations."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.exceptions import ForbiddenError
from app.core.security import create_access_token, hash_password
from app.db.enums import PlatformRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.models.super_admin import SuperAdmin
from app.db.uow import UnitOfWork
from app.services.company import CompanyService
from tests.conftest import auth_header


async def _create_super_admin(
    *,
    email: str | None = None,
    password: str = "super-secret",
) -> SuperAdmin:
    suffix = uuid4().hex[:8]
    email = email or f"sa-{suffix}@test.local"
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        admin = await uow.super_admins.create(
            SuperAdmin(
                email=email,
                full_name="Test Super Admin",
                password_hash=hash_password(password),
                is_active=True,
            ),
        )
        await uow.commit()
        return admin


def _sa_header(admin: SuperAdmin) -> dict[str, str]:
    token = create_access_token(
        subject=admin.id,
        role=PlatformRole.SUPER_ADMIN.value,
        company_id=None,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def super_admin() -> SuperAdmin:
    return await _create_super_admin()


_CREATE_PAYLOAD = {
    "name": "Rogue Tenant",
    "slug": "rogue-tenant",
    "timezone": "UTC",
}


@pytest.mark.asyncio
async def test_super_admin_can_create_company(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
) -> None:
    headers = _sa_header(super_admin)
    slug = f"ok-{uuid4().hex[:8]}"
    with patch(
        "app.services.platform_management.secrets.token_urlsafe",
        side_effect=lambda _n=32: f"invite-{uuid4().hex}",
    ):
        res = await api_client.post(
            "/api/v1/super-admin/companies",
            headers=headers,
            json={
                "name": "Legit Tenant",
                "slug": slug,
                "timezone": "UTC",
                "admin_full_name": "First Admin",
                "admin_email": f"admin@{slug}.test",
                "admin_telegram_user_id": uuid4().int % 1_000_000_000 + 50,
            },
        )
    assert res.status_code == 201, res.text
    assert res.json()["slug"] == slug


@pytest.mark.asyncio
async def test_tenant_admin_cannot_create_company_via_tenant_api(
    api_client: AsyncClient,
    admin_a: Employee,
) -> None:
    res = await api_client.post(
        "/api/v1/companies",
        headers=auth_header(admin_a),
        json={**_CREATE_PAYLOAD, "slug": f"admin-{uuid4().hex[:8]}"},
    )
    assert res.status_code == 403
    assert "Super Admin" in res.json()["detail"]


@pytest.mark.asyncio
async def test_employee_cannot_create_company_via_tenant_api(
    api_client: AsyncClient,
    employee_a: Employee,
) -> None:
    res = await api_client.post(
        "/api/v1/companies",
        headers=auth_header(employee_a),
        json={**_CREATE_PAYLOAD, "slug": f"emp-{uuid4().hex[:8]}"},
    )
    assert res.status_code == 403
    assert "Super Admin" in res.json()["detail"]


@pytest.mark.asyncio
async def test_hr_cannot_create_company_via_tenant_api(
    api_client: AsyncClient,
    hr_a: Employee,
) -> None:
    res = await api_client.post(
        "/api/v1/companies",
        headers=auth_header(hr_a),
        json={**_CREATE_PAYLOAD, "slug": f"hr-{uuid4().hex[:8]}"},
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_anonymous_cannot_create_company(api_client: AsyncClient) -> None:
    res = await api_client.post(
        "/api/v1/companies",
        json={**_CREATE_PAYLOAD, "slug": f"anon-{uuid4().hex[:8]}"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_bot_service_token_cannot_create_company(api_client: AsyncClient) -> None:
    """Bot service token is not a Bearer JWT and must not create tenants."""
    res = await api_client.post(
        "/api/v1/companies",
        headers={"X-Bot-Service-Token": "any-bot-service-token"},
        json={**_CREATE_PAYLOAD, "slug": f"bot-{uuid4().hex[:8]}"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_tenant_jwt_cannot_create_via_platform_api(
    api_client: AsyncClient,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    for user in (admin_a, employee_a):
        res = await api_client.post(
            "/api/v1/super-admin/companies",
            headers=auth_header(user),
            json={
                "name": "Should Fail",
                "slug": f"fail-{uuid4().hex[:8]}",
                "timezone": "UTC",
                "admin_full_name": "X",
                "admin_email": f"x@{uuid4().hex[:8]}.test",
                "admin_telegram_user_id": uuid4().int % 1_000_000_000 + 50,
            },
        )
        assert res.status_code == 401, res.text


@pytest.mark.asyncio
async def test_tenant_admin_cannot_delete_company(
    api_client: AsyncClient,
    admin_a: Employee,
    company_a: Company,
) -> None:
    res = await api_client.delete(
        f"/api/v1/companies/{company_a.id}",
        headers=auth_header(admin_a),
    )
    assert res.status_code == 403
    assert "Super Admin" in res.json()["detail"]


@pytest.mark.asyncio
async def test_tenant_admin_cannot_set_is_active_via_patch(
    api_client: AsyncClient,
    admin_a: Employee,
    company_a: Company,
) -> None:
    res = await api_client.patch(
        f"/api/v1/companies/{company_a.id}",
        headers=auth_header(admin_a),
        json={"is_active": False},
    )
    # Field removed from tenant schema → validation error, not silent accept.
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_company_service_create_and_delete_are_forbidden() -> None:
    service = CompanyService()
    with pytest.raises(ForbiddenError, match="Super Admin"):
        await service.create_company(name="x", slug="x")
    with pytest.raises(ForbiddenError, match="Super Admin"):
        await service.delete_company(uuid4(), actor_company_id=uuid4())
    with pytest.raises(ForbiddenError, match="platform"):
        await service.deactivate_company(uuid4(), actor_company_id=uuid4())
    with pytest.raises(ForbiddenError, match="platform"):
        await service.update_company(
            uuid4(),
            actor_company_id=uuid4(),
            is_active=False,
        )


@pytest.mark.asyncio
async def test_super_admin_token_still_rejected_on_tenant_companies(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
) -> None:
    """Auth realms stay isolated: SA JWT must not use tenant /companies."""
    res = await api_client.post(
        "/api/v1/companies",
        headers=_sa_header(super_admin),
        json={**_CREATE_PAYLOAD, "slug": f"sa-{uuid4().hex[:8]}"},
    )
    assert res.status_code == 401
