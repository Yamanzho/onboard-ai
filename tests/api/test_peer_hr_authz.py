"""SEC-H1: HR must not mutate or delete peer HR accounts.

Authorization uses the target's persisted role from the DB before mutation.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from app.db.models.refresh_session import RefreshSession
from app.services.refresh_session import SUBJECT_EMPLOYEE
from tests.conftest import auth_header, _uow_factory, tenant_tokens_from_response

_PASSWORD = "PeerHrPass1!"
_ATTACKER_TELEGRAM = 999_777_666


async def _create_peer_hr(
    company_id,
    *,
    full_name: str = "Peer HR",
    telegram_user_id: int | None = None,
    password: str = _PASSWORD,
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=telegram_user_id
                or (uuid4().int % 1_000_000_000 + 9200),
                full_name=full_name,
                role=EmployeeRole.HR.value,
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
        return len(list((await uow.session.scalars(stmt)).all()))


async def _login(api_client: AsyncClient, employee_id, password: str = _PASSWORD) -> dict:
    response = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee_id), "password": password},
    )
    assert response.status_code == 200, response.text
    return tenant_tokens_from_response(response)


async def _reload(employee_id) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        row = await uow.employees.get_by_id(employee_id)
        assert row is not None
        return row


# ---------------------------------------------------------------------------
# SEC-H1 — peer HR mutation / deletion closed
# ---------------------------------------------------------------------------


async def test_hr_cannot_modify_peer_hr(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    peer = await _create_peer_hr(company_a.id, full_name="HR Peer Original")
    original_name = peer.full_name

    for payload in (
        {"full_name": "Hijacked Peer HR"},
        {"email": "attacker@evil.test"},
        {"telegram_username": "attacker"},
        {"status": "archived"},
        {"role": "employee"},
    ):
        response = await api_client.patch(
            f"/api/v1/employees/{peer.id}",
            headers=auth_header(hr_a),
            json=payload,
        )
        assert response.status_code == 403, (payload, response.text)

    refreshed = await _reload(peer.id)
    assert refreshed.full_name == original_name
    assert refreshed.role == EmployeeRole.HR.value
    assert refreshed.status == EmployeeStatus.ACTIVE.value


async def test_hr_cannot_rebind_peer_hr_telegram(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Attack path 1: rebind peer HR telegram → bot login as peer HR."""
    bot_token = "test-bot-service-token-sec-h1"
    monkeypatch.setenv("BOT_SERVICE_TOKEN", bot_token)
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", bot_token)
    monkeypatch.setattr(settings, "bot_company_id", str(company_a.id))

    peer_telegram = 92001111
    peer = await _create_peer_hr(
        company_a.id,
        full_name="HR Telegram Target",
        telegram_user_id=peer_telegram,
    )

    response = await api_client.patch(
        f"/api/v1/employees/{peer.id}",
        headers=auth_header(hr_a),
        json={"telegram_user_id": _ATTACKER_TELEGRAM},
    )
    assert response.status_code == 403, response.text

    refreshed = await _reload(peer.id)
    assert refreshed.telegram_user_id == peer_telegram

    # Legitimate bot identity for peer HR still works; attacker id does not.
    bot_headers = {"X-Bot-Service-Token": bot_token}
    legit = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers=bot_headers,
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": peer_telegram,
        },
    )
    assert legit.status_code == 200, legit.text
    assert legit.json()["access_token"]

    attack = await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers=bot_headers,
        json={
            "company_id": str(company_a.id),
            "telegram_user_id": _ATTACKER_TELEGRAM,
        },
    )
    assert attack.status_code == 404, attack.text

    get_settings.cache_clear()


async def test_hr_cannot_demote_peer_hr_then_delete(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    """Attack path 2: demote peer HR to employee, then DELETE."""
    peer = await _create_peer_hr(company_a.id, full_name="HR Demote Target")

    demote = await api_client.patch(
        f"/api/v1/employees/{peer.id}",
        headers=auth_header(hr_a),
        json={"role": "employee"},
    )
    assert demote.status_code == 403, demote.text

    still_hr = await _reload(peer.id)
    assert still_hr.role == EmployeeRole.HR.value

    delete = await api_client.delete(
        f"/api/v1/employees/{peer.id}",
        headers=auth_header(hr_a),
    )
    assert delete.status_code == 403, delete.text

    exists = await _reload(peer.id)
    assert exists.role == EmployeeRole.HR.value
    assert exists.id == peer.id


async def test_hr_cannot_delete_peer_hr(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    peer = await _create_peer_hr(company_a.id, full_name="HR Delete Target")

    response = await api_client.delete(
        f"/api/v1/employees/{peer.id}",
        headers=auth_header(hr_a),
    )
    assert response.status_code == 403, response.text

    exists = await _reload(peer.id)
    assert exists.role == EmployeeRole.HR.value


async def test_admin_can_manage_hr(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
) -> None:
    peer = await _create_peer_hr(company_a.id, full_name="Admin Managed HR")

    rename = await api_client.patch(
        f"/api/v1/employees/{peer.id}",
        headers=auth_header(admin_a),
        json={"full_name": "Renamed By Admin"},
    )
    assert rename.status_code == 200, rename.text
    assert rename.json()["full_name"] == "Renamed By Admin"

    demote = await api_client.patch(
        f"/api/v1/employees/{peer.id}",
        headers=auth_header(admin_a),
        json={"role": "employee"},
    )
    assert demote.status_code == 200, demote.text
    assert demote.json()["role"] == EmployeeRole.EMPLOYEE.value

    delete = await api_client.delete(
        f"/api/v1/employees/{peer.id}",
        headers=auth_header(admin_a),
    )
    assert delete.status_code == 204, delete.text

    async with _uow_factory() as uow:
        await uow.enter_platform()
        assert await uow.employees.get_by_id(peer.id) is None


async def test_hr_can_manage_employee(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    response = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(hr_a),
        json={"full_name": "Updated By HR"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Updated By HR"

    archived = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(hr_a),
        json={"status": "archived"},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == EmployeeStatus.ARCHIVED.value


async def test_hr_cannot_modify_admin(
    api_client: AsyncClient,
    hr_a: Employee,
    admin_a: Employee,
) -> None:
    response = await api_client.patch(
        f"/api/v1/employees/{admin_a.id}",
        headers=auth_header(hr_a),
        json={"telegram_user_id": _ATTACKER_TELEGRAM},
    )
    assert response.status_code == 403, response.text

    delete = await api_client.delete(
        f"/api/v1/employees/{admin_a.id}",
        headers=auth_header(hr_a),
    )
    assert delete.status_code == 403, delete.text


async def test_cross_tenant_hr_targeting_remains_404(
    api_client: AsyncClient,
    company_b,
    hr_a: Employee,
) -> None:
    foreign_hr = await _create_peer_hr(company_b.id, full_name="Foreign HR")

    patch = await api_client.patch(
        f"/api/v1/employees/{foreign_hr.id}",
        headers=auth_header(hr_a),
        json={"full_name": "Cross Tenant"},
    )
    assert patch.status_code == 404, patch.text

    delete = await api_client.delete(
        f"/api/v1/employees/{foreign_hr.id}",
        headers=auth_header(hr_a),
    )
    assert delete.status_code == 404, delete.text

    exists = await _reload(foreign_hr.id)
    assert exists.full_name == "Foreign HR"
    assert exists.role == EmployeeRole.HR.value


async def test_peer_hr_sessions_untouched_after_rejected_ops(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    peer = await _create_peer_hr(company_a.id, full_name="HR Session Target")
    tokens = await _login(api_client, peer.id)
    sessions_before = await _count_active_sessions(peer.id)
    assert sessions_before >= 1

    for payload in (
        {"telegram_user_id": _ATTACKER_TELEGRAM},
        {"role": "employee"},
        {"status": "archived"},
        {"full_name": "Should Not Apply"},
    ):
        response = await api_client.patch(
            f"/api/v1/employees/{peer.id}",
            headers=auth_header(hr_a),
            json=payload,
        )
        assert response.status_code == 403, (payload, response.text)

    delete = await api_client.delete(
        f"/api/v1/employees/{peer.id}",
        headers=auth_header(hr_a),
    )
    assert delete.status_code == 403, delete.text

    assert await _count_active_sessions(peer.id) == sessions_before

    me = await api_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["id"] == str(peer.id)
    assert me.json()["role"] == EmployeeRole.HR.value

    refresh = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refresh.status_code == 200, refresh.text

    refreshed = await _reload(peer.id)
    assert refreshed.role == EmployeeRole.HR.value
    assert refreshed.status == EmployeeStatus.ACTIVE.value
    assert refreshed.full_name == "HR Session Target"
