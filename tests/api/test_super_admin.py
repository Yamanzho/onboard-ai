"""API tests for platform Super Admin panel endpoints."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, hash_password
from app.db.enums import EmployeeRole, EmployeeStatus, PlatformRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.models.super_admin import SuperAdmin
from app.db.uow import UnitOfWork
from tests.conftest import auth_header, sa_tokens_from_response


async def _create_super_admin(
    *,
    email: str | None = None,
    password: str = "super-secret",
) -> tuple[SuperAdmin, str]:
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
        return admin, password


def _sa_header(admin: SuperAdmin) -> dict[str, str]:
    token = create_access_token(
        subject=admin.id,
        role=PlatformRole.SUPER_ADMIN.value,
        company_id=None,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def super_admin() -> SuperAdmin:
    admin, _ = await _create_super_admin()
    return admin


@pytest.mark.asyncio
async def test_super_admin_login_and_me(api_client: AsyncClient) -> None:
    admin, password = await _create_super_admin()

    bad = await api_client.post(
        "/api/v1/super-admin/auth/login",
        json={"email": admin.email, "password": "wrong"},
    )
    assert bad.status_code == 401

    login = await api_client.post(
        "/api/v1/super-admin/auth/login",
        json={"email": admin.email, "password": password},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    assert "access_token" not in body
    assert "refresh_token" not in body
    tokens = sa_tokens_from_response(login)

    me = await api_client.get(
        "/api/v1/super-admin/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == admin.email
    assert body["role"] == PlatformRole.SUPER_ADMIN.value


@pytest.mark.asyncio
async def test_super_admin_token_cannot_access_tenant_api(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
) -> None:
    headers = _sa_header(super_admin)
    res = await api_client.get(
        "/api/v1/companies",
        headers=headers,
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_company_admin_cannot_access_super_admin_api(
    api_client: AsyncClient,
    hr_a: Employee,
) -> None:
    headers = auth_header(hr_a)
    res = await api_client.get("/api/v1/super-admin/dashboard", headers=headers)
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_and_company_lifecycle(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
) -> None:
    headers = _sa_header(super_admin)

    stats = await api_client.get("/api/v1/super-admin/dashboard", headers=headers)
    assert stats.status_code == 200, stats.text
    data = stats.json()
    assert data["companies_count"] >= 1
    assert "employees_count" in data
    assert "active_companies" in data
    assert "trial_companies" in data
    assert "expired_companies" in data
    assert "active_assignments_count" in data

    listed = await api_client.get("/api/v1/super-admin/companies", headers=headers)
    assert listed.status_code == 200
    ids = {c["id"] for c in listed.json()}
    assert str(company_a.id) in ids

    slug = f"new-{uuid4().hex[:8]}"
    admin_email = f"admin@{slug}.test"
    invite_token = f"invite-{uuid4().hex}"
    with patch(
        "app.services.platform_management.secrets.token_urlsafe",
        return_value=invite_token,
    ):
        create = await api_client.post(
            "/api/v1/super-admin/companies",
            headers=headers,
            json={
                "name": "New Tenant",
                "slug": slug,
                "timezone": "UTC",
                "admin_full_name": "First Admin",
                "admin_email": admin_email,
                "admin_telegram_user_id": uuid4().int % 1_000_000_000 + 50,
            },
        )
    assert create.status_code == 201, create.text
    company = create.json()
    assert company["slug"] == slug
    assert company["employees_count"] == 1
    assert company["subscription"] is not None
    assert company["subscription"]["status"] == "trial"
    assert company["limits"] is not None

    company_id = company["id"]
    detail = await api_client.get(
        f"/api/v1/super-admin/companies/{company_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["contact_email"] is None

    deactivate = await api_client.post(
        f"/api/v1/super-admin/companies/{company_id}/deactivate",
        headers=headers,
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    activate = await api_client.post(
        f"/api/v1/super-admin/companies/{company_id}/activate",
        headers=headers,
    )
    assert activate.status_code == 200
    assert activate.json()["is_active"] is True

    rename = await api_client.patch(
        f"/api/v1/super-admin/companies/{company_id}",
        headers=headers,
        json={"name": "Renamed Tenant"},
    )
    assert rename.status_code == 200
    assert rename.json()["name"] == "Renamed Tenant"

    preview = await api_client.post(
        "/api/v1/auth/invite/preview",
        json={"token": invite_token},
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["email"] == admin_email

    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": invite_token, "password": "new-secure-password"},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == EmployeeStatus.ACTIVE.value

    login = await api_client.post(
        "/api/v1/auth/login",
        data={
            "username": accept.json()["id"],
            "password": "new-secure-password",
        },
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_subscription_history_and_audit(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
) -> None:
    headers = _sa_header(super_admin)
    company_id = str(company_a.id)

    detail = await api_client.get(
        f"/api/v1/super-admin/companies/{company_id}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["subscription"] is not None

    updated = await api_client.patch(
        f"/api/v1/super-admin/companies/{company_id}/subscription",
        headers=headers,
        json={"status": "active", "payment_status": "paid"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["status"] == "active"
    assert updated.json()["payment_status"] == "paid"

    history = await api_client.get(
        f"/api/v1/super-admin/companies/{company_id}/subscription/history",
        headers=headers,
    )
    assert history.status_code == 200
    assert len(history.json()) >= 1

    limits = await api_client.get(
        f"/api/v1/super-admin/companies/{company_id}/limits",
        headers=headers,
    )
    assert limits.status_code == 200
    assert "employees_used" in limits.json()

    audit = await api_client.get("/api/v1/super-admin/audit-logs", headers=headers)
    assert audit.status_code == 200
    assert len(audit.json()) >= 1


@pytest.mark.asyncio
async def test_users_role_and_block(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
    company_a: Company,
    hr_a: Employee,
) -> None:
    headers = _sa_header(super_admin)

    users = await api_client.get("/api/v1/super-admin/users", headers=headers)
    assert users.status_code == 200
    ids = {u["id"] for u in users.json()}
    assert str(hr_a.id) in ids

    updated = await api_client.patch(
        f"/api/v1/super-admin/users/{hr_a.id}",
        headers=headers,
        json={"role": EmployeeRole.ADMIN.value},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["role"] == EmployeeRole.ADMIN.value

    blocked = await api_client.post(
        f"/api/v1/super-admin/users/{hr_a.id}/block",
        headers=headers,
    )
    assert blocked.status_code == 200
    assert blocked.json()["status"] == EmployeeStatus.ARCHIVED.value


@pytest.mark.asyncio
async def test_settings_stub(
    api_client: AsyncClient,
    super_admin: SuperAdmin,
) -> None:
    headers = _sa_header(super_admin)
    get_res = await api_client.get("/api/v1/super-admin/settings", headers=headers)
    assert get_res.status_code == 200

    patch = await api_client.patch(
        "/api/v1/super-admin/settings",
        headers=headers,
        json={"maintenance_mode": True},
    )
    assert patch.status_code == 200
    assert patch.json()["maintenance_mode"] is True
