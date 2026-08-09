"""SEC-M7: refresh endpoints are rate-limited before rotation."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limiter_state_for_tests
from app.core.security import hash_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from app.db.models.refresh_session import RefreshSession
from app.db.models.super_admin import SuperAdmin
from app.main import app
from app.services.refresh_session import SUBJECT_EMPLOYEE
from sqlalchemy import select
from tests.conftest import _uow_factory, sa_tokens_from_response, tenant_tokens_from_response

_PASSWORD = "RefreshRlPass1!"


async def _create_active_employee(company_id) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 9400,
                full_name="Refresh RL User",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ACTIVE.value,
                password_hash=hash_password(_PASSWORD),
            ),
        )
        await uow.commit()
        return employee


async def _login_tenant(client: AsyncClient, employee_id) -> dict:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": str(employee_id), "password": _PASSWORD},
    )
    assert response.status_code == 200, response.text
    return tenant_tokens_from_response(response)


async def _login_sa(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/v1/super-admin/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return sa_tokens_from_response(response)


async def _count_active_sessions(subject_type: str, subject_id) -> int:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        stmt = select(RefreshSession).where(
            RefreshSession.subject_type == subject_type,
            RefreshSession.subject_id == subject_id,
            RefreshSession.revoked_at.is_(None),
        )
        return len(list((await uow.session.scalars(stmt)).all()))


@pytest.fixture
def isolated_client() -> str:
    """Unique client host so rate-limit keys do not collide across tests."""
    return f"203.0.113.{(uuid4().int % 200) + 1}"


async def test_refresh_within_limit_succeeds(
    company_a,
    isolated_client: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "refresh_rate_limit", 5)
    monkeypatch.setattr(settings, "refresh_rate_window_seconds", 60)

    employee = await _create_active_employee(company_a.id)
    transport = ASGITransport(app=app, client=(isolated_client, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _login_tenant(client, employee.id)
            refresh = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            )
            assert refresh.status_code == 200, refresh.text
            assert refresh.json()["refresh_token"]
            assert refresh.json()["refresh_token"] != tokens["refresh_token"]
    finally:
        reset_rate_limiter_state_for_tests()
        settings.refresh_rate_limit = 0


async def test_excessive_tenant_refresh_returns_429(
    company_a,
    isolated_client: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "refresh_rate_limit", 2)
    monkeypatch.setattr(settings, "refresh_rate_window_seconds", 60)

    employee = await _create_active_employee(company_a.id)
    transport = ASGITransport(app=app, client=(isolated_client, 54321))
    statuses: list[int] = []
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _login_tenant(client, employee.id)
            current = tokens["refresh_token"]
            for _ in range(3):
                res = await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": current},
                )
                statuses.append(res.status_code)
                if res.status_code == 200:
                    current = res.json()["refresh_token"]
    finally:
        reset_rate_limiter_state_for_tests()
        settings.refresh_rate_limit = 0

    assert statuses[0] == 200
    assert statuses[1] == 200
    assert statuses[2] == 429


async def test_excessive_sa_refresh_returns_429(
    isolated_client: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "refresh_rate_limit", 2)
    monkeypatch.setattr(settings, "refresh_rate_window_seconds", 60)

    password = "SaRefreshRl1!"
    suffix = uuid4().hex[:8]
    async with _uow_factory() as uow:
        await uow.enter_platform()
        admin = await uow.super_admins.create(
            SuperAdmin(
                email=f"sa-rl-{suffix}@test.local",
                full_name="SA RL",
                password_hash=hash_password(password),
                is_active=True,
            ),
        )
        await uow.commit()

    transport = ASGITransport(app=app, client=(isolated_client, 54321))
    statuses: list[int] = []
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _login_sa(client, admin.email, password)
            current = tokens["refresh_token"]
            for _ in range(3):
                res = await client.post(
                    "/api/v1/super-admin/auth/refresh",
                    json={"refresh_token": current},
                )
                statuses.append(res.status_code)
                if res.status_code == 200:
                    current = res.json()["refresh_token"]
    finally:
        reset_rate_limiter_state_for_tests()
        settings.refresh_rate_limit = 0

    assert statuses[0] == 200
    assert statuses[1] == 200
    assert statuses[2] == 429


async def test_tenant_and_sa_refresh_rate_limit_keys_separated(
    company_a,
    isolated_client: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "refresh_rate_limit", 2)
    monkeypatch.setattr(settings, "refresh_rate_window_seconds", 60)

    employee = await _create_active_employee(company_a.id)
    password = "SaRefreshSep1!"
    suffix = uuid4().hex[:8]
    async with _uow_factory() as uow:
        await uow.enter_platform()
        admin = await uow.super_admins.create(
            SuperAdmin(
                email=f"sa-sep-{suffix}@test.local",
                full_name="SA Sep",
                password_hash=hash_password(password),
                is_active=True,
            ),
        )
        await uow.commit()

    transport = ASGITransport(app=app, client=(isolated_client, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tenant = await _login_tenant(client, employee.id)
            current = tenant["refresh_token"]
            for _ in range(2):
                res = await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": current},
                )
                assert res.status_code == 200, res.text
                current = res.json()["refresh_token"]
            blocked = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": current},
            )
            assert blocked.status_code == 429

            # Same IP, different key — SA refresh still allowed.
            sa = await _login_sa(client, admin.email, password)
            sa_refresh = await client.post(
                "/api/v1/super-admin/auth/refresh",
                json={"refresh_token": sa["refresh_token"]},
            )
            assert sa_refresh.status_code == 200, sa_refresh.text
    finally:
        reset_rate_limiter_state_for_tests()
        settings.refresh_rate_limit = 0


async def test_refresh_429_does_not_revoke_token(
    company_a,
    isolated_client: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "refresh_rate_limit", 1)
    monkeypatch.setattr(settings, "refresh_rate_window_seconds", 60)

    employee = await _create_active_employee(company_a.id)
    transport = ASGITransport(app=app, client=(isolated_client, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _login_tenant(client, employee.id)
            first = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            )
            assert first.status_code == 200, first.text
            live = first.json()["refresh_token"]
            sessions_before = await _count_active_sessions(SUBJECT_EMPLOYEE, employee.id)

            limited = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": live},
            )
            assert limited.status_code == 429
            assert await _count_active_sessions(SUBJECT_EMPLOYEE, employee.id) == sessions_before

            # Clear limiter without touching sessions — presented token must still rotate.
            reset_rate_limiter_state_for_tests()
            monkeypatch.setattr(settings, "refresh_rate_limit", 5)
            recovered = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": live},
            )
            assert recovered.status_code == 200, recovered.text
            assert recovered.json()["refresh_token"] != live
    finally:
        reset_rate_limiter_state_for_tests()
        settings.refresh_rate_limit = 0


async def test_refresh_works_after_rate_limit_window_expires(
    company_a,
    isolated_client: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "refresh_rate_limit", 1)
    monkeypatch.setattr(settings, "refresh_rate_window_seconds", 1)

    employee = await _create_active_employee(company_a.id)
    transport = ASGITransport(app=app, client=(isolated_client, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _login_tenant(client, employee.id)
            first = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": tokens["refresh_token"]},
            )
            assert first.status_code == 200, first.text
            live = first.json()["refresh_token"]

            limited = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": live},
            )
            assert limited.status_code == 429

            await asyncio.sleep(2.0)
            recovered = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": live},
            )
            assert recovered.status_code == 200, recovered.text
    finally:
        reset_rate_limiter_state_for_tests()
        settings.refresh_rate_limit = 0


async def test_refresh_rate_limit_ignores_xff_when_trust_disabled(
    company_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """User-controlled X-Forwarded-For must not bypass the limiter."""
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "trust_proxy_headers", False)
    monkeypatch.setattr(settings, "refresh_rate_limit", 2)
    monkeypatch.setattr(settings, "refresh_rate_window_seconds", 60)

    employee = await _create_active_employee(company_a.id)
    host = f"198.51.100.{(uuid4().int % 200) + 1}"
    transport = ASGITransport(app=app, client=(host, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _login_tenant(client, employee.id)
            current = tokens["refresh_token"]
            statuses: list[int] = []
            for i in range(3):
                res = await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": current},
                    headers={"X-Forwarded-For": f"203.0.113.{i + 10}"},
                )
                statuses.append(res.status_code)
                if res.status_code == 200:
                    current = res.json()["refresh_token"]
    finally:
        reset_rate_limiter_state_for_tests()
        settings.refresh_rate_limit = 0

    assert statuses[0] == 200
    assert statuses[1] == 200
    assert statuses[2] == 429


async def test_refresh_rate_limit_ignores_spoofed_xff_when_trust_enabled(
    company_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-R1: trust on + X-Real-IP peer; rotating XFF must not bypass refresh RL."""
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    monkeypatch.setattr(settings, "refresh_rate_limit", 2)
    monkeypatch.setattr(settings, "refresh_rate_window_seconds", 60)

    employee = await _create_active_employee(company_a.id)
    peer = f"198.51.100.{(uuid4().int % 200) + 1}"
    transport = ASGITransport(app=app, client=(peer, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            tokens = await _login_tenant(client, employee.id)
            current = tokens["refresh_token"]
            statuses: list[int] = []
            for i in range(3):
                res = await client.post(
                    "/api/v1/auth/refresh",
                    json={"refresh_token": current},
                    headers={
                        "X-Forwarded-For": f"203.0.113.{i + 10}",
                        "X-Real-IP": peer,
                    },
                )
                statuses.append(res.status_code)
                if res.status_code == 200:
                    current = res.json()["refresh_token"]
    finally:
        reset_rate_limiter_state_for_tests()
        settings.refresh_rate_limit = 0

    assert statuses[0] == 200
    assert statuses[1] == 200
    assert statuses[2] == 429
