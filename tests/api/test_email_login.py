"""Email-based tenant login (UUID still accepted for backward compatibility)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limiter_state_for_tests
from app.core.security import hash_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from app.main import app
from tests.conftest import auth_header, _uow_factory, tenant_tokens_from_response

_PASSWORD = "EmailLogin1!"


async def _create(
    company_id,
    *,
    email: str,
    password: str = _PASSWORD,
    status: str = EmployeeStatus.ACTIVE.value,
    role: str = EmployeeRole.ADMIN.value,
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 3000,
                full_name="Email Login User",
                email=email,
                role=role,
                status=status,
                password_hash=hash_password(password)
                if status == EmployeeStatus.ACTIVE.value
                else None,
            ),
        )
        await uow.commit()
        return employee


async def test_login_by_email_success(
    api_client: AsyncClient,
    company_a,
) -> None:
    email = f"login-{uuid4().hex[:8]}@example.com"
    employee = await _create(company_a.id, email=email)
    res = await api_client.post(
        "/api/v1/auth/login",
        data={"username": email.upper(), "password": _PASSWORD},
    )
    assert res.status_code == 200, res.text
    assert "access_token" not in res.json()
    tokens = tenant_tokens_from_response(res)
    me = await api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["id"] == str(employee.id)
    assert me.json()["email"] == email.lower()


async def test_login_by_email_wrong_password_same_as_unknown(
    api_client: AsyncClient,
    company_a,
) -> None:
    email = f"wrong-{uuid4().hex[:8]}@example.com"
    await _create(company_a.id, email=email)

    wrong = await api_client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "NotThePass1!"},
    )
    unknown = await api_client.post(
        "/api/v1/auth/login",
        data={"username": f"missing-{uuid4().hex[:8]}@example.com", "password": "NotThePass1!"},
    )
    assert wrong.status_code == 401
    assert unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"] == "Invalid credentials"


async def test_login_by_email_invited_and_archived(
    api_client: AsyncClient,
    company_a,
) -> None:
    invited_email = f"invited-{uuid4().hex[:8]}@example.com"
    archived_email = f"archived-{uuid4().hex[:8]}@example.com"
    await _create(
        company_a.id,
        email=invited_email,
        status=EmployeeStatus.INVITED.value,
    )
    archived = await _create(company_a.id, email=archived_email)
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employees.update(
            archived.id,
            status=EmployeeStatus.ARCHIVED.value,
        )
        await uow.commit()

    # Invited has no password_hash — wrong credentials → 401 (no enumeration).
    invited_res = await api_client.post(
        "/api/v1/auth/login",
        data={"username": invited_email, "password": _PASSWORD},
    )
    assert invited_res.status_code == 401

    # Give invited a hash so correct-password path can surface invite gate.
    async with _uow_factory() as uow:
        await uow.enter_platform()
        invited_row = await uow.employees.get_by_email(invited_email)
        assert invited_row is not None
        await uow.employees.update(
            invited_row.id,
            password_hash=hash_password(_PASSWORD),
        )
        await uow.commit()

    invited_ok_pw = await api_client.post(
        "/api/v1/auth/login",
        data={"username": invited_email, "password": _PASSWORD},
    )
    assert invited_ok_pw.status_code == 403
    assert "invite" in invited_ok_pw.json()["detail"].lower()

    archived_res = await api_client.post(
        "/api/v1/auth/login",
        data={"username": archived_email, "password": _PASSWORD},
    )
    assert archived_res.status_code == 403
    assert "archived" in archived_res.json()["detail"].lower()


async def test_login_legacy_uuid_still_works(
    api_client: AsyncClient,
    company_a,
) -> None:
    email = f"uuid-compat-{uuid4().hex[:8]}@example.com"
    employee = await _create(company_a.id, email=email)
    res = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee.id), "password": _PASSWORD},
    )
    assert res.status_code == 200, res.text


async def test_cross_tenant_same_email_blocked_by_unique_index(
    api_client: AsyncClient,
    company_a,
    company_b,
) -> None:
    email = f"shared-{uuid4().hex[:8]}@example.com"
    await _create(company_a.id, email=email)
    with pytest.raises(Exception):
        await _create(company_b.id, email=email)


async def test_invite_accept_then_email_login(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
) -> None:
    email = f"invite-login-{uuid4().hex[:8]}@example.com"
    create = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "full_name": "Invite Then Login",
            "email": email,
            "role": "hr",
            "status": "invited",
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["invite_url"]
    token = body["invite_url"].rsplit("#", 1)[1]
    password = "AfterInvite9!"

    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": password},
    )
    assert accept.status_code == 200, accept.text

    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    assert login.status_code == 200, login.text
    tokens = tenant_tokens_from_response(login)
    refresh = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh.status_code == 200, refresh.text


async def test_email_login_rate_limited(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "login_rate_limit", 2)
    monkeypatch.setattr(settings, "login_rate_window_seconds", 60)

    client_host = f"203.0.113.{(uuid4().int % 200) + 1}"
    transport = ASGITransport(app=app, client=(client_host, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            statuses: list[int] = []
            for _ in range(3):
                res = await client.post(
                    "/api/v1/auth/login",
                    data={
                        "username": f"rl-{uuid4().hex[:8]}@example.com",
                        "password": "Whatever1!",
                    },
                )
                statuses.append(res.status_code)
    finally:
        reset_rate_limiter_state_for_tests()
        settings.login_rate_limit = 0

    assert statuses[0] == 401
    assert statuses[1] == 401
    assert statuses[2] == 429
