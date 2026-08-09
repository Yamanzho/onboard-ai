"""P1 session hardening: archive revoke, bot invite gate, password, logout-all, invite RL."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.rate_limit import reset_rate_limiter_state_for_tests
from app.core.security import hash_password, verify_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from app.db.models.refresh_session import RefreshSession
from app.main import app
from app.services.refresh_session import SUBJECT_EMPLOYEE, RefreshSessionService
from tests.conftest import auth_header, _uow_factory, tenant_tokens_from_response

_PASSWORD = "SecurePass1!"
_NEW_PASSWORD = "SecurePass2!"


async def _create_active_employee(
    company_id,
    *,
    password: str = _PASSWORD,
    role: str = EmployeeRole.EMPLOYEE.value,
    telegram_user_id: int | None = None,
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=telegram_user_id or (uuid4().int % 1_000_000_000 + 8000),
                full_name="Session Harden User",
                role=role,
                status=EmployeeStatus.ACTIVE.value,
                password_hash=hash_password(password),
            ),
        )
        await uow.commit()
        return employee


async def _count_active_sessions(subject_id) -> int:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        stmt = select(RefreshSession).where(
            RefreshSession.subject_type == SUBJECT_EMPLOYEE,
            RefreshSession.subject_id == subject_id,
            RefreshSession.revoked_at.is_(None),
        )
        rows = list((await uow.session.scalars(stmt)).all())
        return len(rows)


async def _login(api_client: AsyncClient, employee_id, password: str = _PASSWORD) -> dict:
    response = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee_id), "password": password},
    )
    assert response.status_code == 200, response.text
    assert "access_token" not in response.json()
    assert "refresh_token" not in response.json()
    return tenant_tokens_from_response(response)


# ---------------------------------------------------------------------------
# A. Archive employee → access 403, refresh rejected, sessions revoked
# ---------------------------------------------------------------------------


async def test_archive_employee_revokes_sessions_and_blocks_access(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
) -> None:
    target = await _create_active_employee(company_a.id)
    tokens = await _login(api_client, target.id)
    access = tokens["access_token"]
    refresh = tokens["refresh_token"]
    # Second family so we prove revoke_all, not single-session logout.
    second = await RefreshSessionService().issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=target.id,
        role=target.role,
        company_id=target.company_id,
    )
    assert await _count_active_sessions(target.id) >= 2

    archive = await api_client.patch(
        f"/api/v1/employees/{target.id}",
        headers=auth_header(admin_a),
        json={"status": "archived"},
    )
    assert archive.status_code == 200, archive.text
    assert archive.json()["status"] == EmployeeStatus.ARCHIVED.value
    assert await _count_active_sessions(target.id) == 0

    me = await api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access}"},
    )
    assert me.status_code == 403
    assert "archived" in me.json()["detail"].lower()

    for raw in (refresh, second.tokens.refresh_token):
        replay = await api_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": raw},
        )
        assert replay.status_code == 401, replay.text


# ---------------------------------------------------------------------------
# B. Bot login status gates
# ---------------------------------------------------------------------------


@pytest.fixture
def bot_service_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-bot-service-token-p1-harden"
    monkeypatch.setenv("BOT_SERVICE_TOKEN", token)
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", token)
    yield token
    get_settings.cache_clear()


async def test_bot_login_rejects_invited_allows_active_rejects_archived(
    api_client: AsyncClient,
    company_a,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_company_id", str(company_a.id))
    monkeypatch.setattr(settings, "bot_service_token", bot_service_token)

    async with _uow_factory() as uow:
        await uow.enter_platform()
        invited = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                telegram_user_id=91006001,
                full_name="Bot Invited",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.INVITED.value,
            ),
        )
        active = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                telegram_user_id=91006002,
                full_name="Bot Active",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ACTIVE.value,
                password_hash=hash_password(_PASSWORD),
            ),
        )
        archived = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                telegram_user_id=91006003,
                full_name="Bot Archived",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ARCHIVED.value,
                password_hash=hash_password(_PASSWORD),
            ),
        )
        await uow.commit()

    headers = {"X-Bot-Service-Token": bot_service_token}

    invited_res = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers=headers,
        json={"company_id": str(company_a.id), "telegram_user_id": invited.telegram_user_id},
    )
    assert invited_res.status_code == 403
    assert "invite" in invited_res.json()["detail"].lower()

    active_res = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers=headers,
        json={"company_id": str(company_a.id), "telegram_user_id": active.telegram_user_id},
    )
    assert active_res.status_code == 200, active_res.text
    body = active_res.json()
    assert body["access_token"]
    assert body["refresh_token"]

    archived_res = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers=headers,
        json={"company_id": str(company_a.id), "telegram_user_id": archived.telegram_user_id},
    )
    assert archived_res.status_code == 403
    assert "archived" in archived_res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# C. Password change
# ---------------------------------------------------------------------------


async def test_password_change_verifies_revokes_and_updates_hash(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _create_active_employee(company_a.id)
    tokens = await _login(api_client, employee.id)
    second = await RefreshSessionService().issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=employee.id,
        role=employee.role,
        company_id=employee.company_id,
    )
    assert await _count_active_sessions(employee.id) >= 2

    wrong = await api_client.post(
        "/api/v1/auth/password",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"current_password": "WrongPass1!", "new_password": _NEW_PASSWORD},
    )
    assert wrong.status_code == 401
    assert await _count_active_sessions(employee.id) >= 2

    ok = await api_client.post(
        "/api/v1/auth/password",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        json={"current_password": _PASSWORD, "new_password": _NEW_PASSWORD},
    )
    assert ok.status_code == 204, ok.text
    assert await _count_active_sessions(employee.id) == 0

    async with _uow_factory() as uow:
        await uow.enter_platform()
        refreshed = await uow.employees.get_by_id(employee.id)
        assert refreshed is not None
        assert verify_password(_NEW_PASSWORD, refreshed.password_hash)
        assert not verify_password(_PASSWORD, refreshed.password_hash)

    old_login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee.id), "password": _PASSWORD},
    )
    assert old_login.status_code == 401

    new_login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee.id), "password": _NEW_PASSWORD},
    )
    assert new_login.status_code == 200, new_login.text

    for raw in (tokens["refresh_token"], second.tokens.refresh_token):
        replay = await api_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": raw},
        )
        assert replay.status_code == 401, replay.text


# ---------------------------------------------------------------------------
# D. Logout-all
# ---------------------------------------------------------------------------


async def test_logout_all_revokes_only_current_subject(
    api_client: AsyncClient,
    company_a,
) -> None:
    user_a = await _create_active_employee(company_a.id, telegram_user_id=91007001)
    user_b = await _create_active_employee(company_a.id, telegram_user_id=91007002)

    tokens_a1 = await _login(api_client, user_a.id)
    tokens_a2 = await RefreshSessionService().issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=user_a.id,
        role=user_a.role,
        company_id=user_a.company_id,
    )
    tokens_b = await _login(api_client, user_b.id)

    logout = await api_client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {tokens_a1['access_token']}"},
    )
    assert logout.status_code == 204, logout.text
    assert await _count_active_sessions(user_a.id) == 0
    assert await _count_active_sessions(user_b.id) >= 1

    for raw in (tokens_a1["refresh_token"], tokens_a2.tokens.refresh_token):
        replay = await api_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": raw},
        )
        assert replay.status_code == 401, replay.text

    still_ok = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens_b["refresh_token"]},
    )
    assert still_ok.status_code == 200, still_ok.text


# ---------------------------------------------------------------------------
# E. Invite rate limiting
# ---------------------------------------------------------------------------


async def test_invite_accept_and_preview_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    monkeypatch.setattr(settings, "invite_accept_rate_limit", 2)
    monkeypatch.setattr(settings, "invite_accept_rate_window_seconds", 60)
    monkeypatch.setattr(settings, "invite_preview_rate_limit", 2)
    monkeypatch.setattr(settings, "invite_preview_rate_window_seconds", 60)

    client_host = f"198.51.100.{(uuid4().int % 200) + 1}"
    transport = ASGITransport(app=app, client=(client_host, 54321))
    fake_token = f"rate-limit-token-{uuid4().hex}"

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            accept_statuses: list[int] = []
            for _ in range(3):
                res = await client.post(
                    "/api/v1/auth/invite/accept",
                    json={"token": fake_token, "password": "Whatever1!"},
                )
                accept_statuses.append(res.status_code)

            preview_statuses: list[int] = []
            for _ in range(3):
                res = await client.post(
                    "/api/v1/auth/invite/preview",
                    json={"token": fake_token},
                )
                preview_statuses.append(res.status_code)
    finally:
        reset_rate_limiter_state_for_tests()
        settings.invite_accept_rate_limit = 0
        settings.invite_preview_rate_limit = 0

    assert accept_statuses[0] in {400, 404}
    assert accept_statuses[1] in {400, 404}
    assert accept_statuses[2] == 429

    assert preview_statuses[0] in {400, 404}
    assert preview_statuses[1] in {400, 404}
    assert preview_statuses[2] == 429


# ---------------------------------------------------------------------------
# F. Tenant isolation — logout-all cannot touch another tenant's sessions
# ---------------------------------------------------------------------------


async def test_logout_all_does_not_revoke_other_tenant_sessions(
    api_client: AsyncClient,
    company_a,
    company_b,
    admin_a: Employee,
) -> None:
    emp_a = await _create_active_employee(company_a.id, telegram_user_id=91008001)
    emp_b = await _create_active_employee(company_b.id, telegram_user_id=91008002)

    tokens_a = await _login(api_client, emp_a.id)
    tokens_b = await _login(api_client, emp_b.id)

    logout = await api_client.post(
        "/api/v1/auth/logout-all",
        headers={"Authorization": f"Bearer {tokens_a['access_token']}"},
    )
    assert logout.status_code == 204
    assert await _count_active_sessions(emp_a.id) == 0
    assert await _count_active_sessions(emp_b.id) >= 1

    still_ok = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens_b["refresh_token"]},
    )
    assert still_ok.status_code == 200, still_ok.text

    # Cross-tenant archive via tenant admin must 404 and not revoke victim sessions.
    victim_sessions = await _count_active_sessions(emp_b.id)
    denied = await api_client.patch(
        f"/api/v1/employees/{emp_b.id}",
        headers=auth_header(admin_a),
        json={"status": "archived"},
    )
    assert denied.status_code == 404
    assert await _count_active_sessions(emp_b.id) == victim_sessions


# ---------------------------------------------------------------------------
# L1. Hard-delete revokes refresh sessions
# ---------------------------------------------------------------------------


async def test_hard_delete_revokes_sessions_and_rejects_refresh(
    api_client: AsyncClient,
    company_a,
    company_b,
    admin_a: Employee,
) -> None:
    target = await _create_active_employee(company_a.id, telegram_user_id=91009001)
    peer = await _create_active_employee(company_a.id, telegram_user_id=91009002)
    foreign = await _create_active_employee(company_b.id, telegram_user_id=91009003)

    target_tokens = await _login(api_client, target.id)
    second = await RefreshSessionService().issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=target.id,
        role=target.role,
        company_id=target.company_id,
    )
    peer_tokens = await _login(api_client, peer.id)
    foreign_tokens = await _login(api_client, foreign.id)
    assert await _count_active_sessions(target.id) >= 2

    deleted = await api_client.delete(
        f"/api/v1/employees/{target.id}",
        headers=auth_header(admin_a),
    )
    assert deleted.status_code == 204, deleted.text
    assert await _count_active_sessions(target.id) == 0

    for raw in (target_tokens["refresh_token"], second.tokens.refresh_token):
        replay = await api_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": raw},
        )
        assert replay.status_code == 401, replay.text

    peer_ok = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": peer_tokens["refresh_token"]},
    )
    assert peer_ok.status_code == 200, peer_ok.text
    assert await _count_active_sessions(peer.id) >= 1

    foreign_ok = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": foreign_tokens["refresh_token"]},
    )
    assert foreign_ok.status_code == 200, foreign_ok.text
    assert await _count_active_sessions(foreign.id) >= 1

    # Cross-tenant delete remains rejected and does not revoke foreign sessions.
    foreign_sessions = await _count_active_sessions(foreign.id)
    cross = await api_client.delete(
        f"/api/v1/employees/{foreign.id}",
        headers=auth_header(admin_a),
    )
    assert cross.status_code == 404
    assert await _count_active_sessions(foreign.id) == foreign_sessions
