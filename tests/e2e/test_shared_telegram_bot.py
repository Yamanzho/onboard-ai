"""Shared Telegram bot: identity, binding, and cross-tenant isolation.

One bot process resolves employees in any company from from_user.id.
Tenant is always employee.company_id from the database.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from tests.conftest import _uow_factory, auth_header

def _tg_id(bucket: int) -> int:
    return uuid4().int % 1_000_000_000 + bucket

pytestmark = [pytest.mark.security, pytest.mark.telegram]


@pytest.fixture
def bot_service_token(monkeypatch: pytest.MonkeyPatch) -> str:
    token = "test-shared-bot-service-token-32c"
    monkeypatch.setenv("BOT_SERVICE_TOKEN", token)
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", token)
    settings.bot_login_rate_limit = 0
    return token


async def _create_employee(
    company_id,
    *,
    telegram_user_id: int,
    status: str = EmployeeStatus.ACTIVE.value,
    full_name: str = "Shared Bot Employee",
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=telegram_user_id,
                full_name=full_name,
                role=EmployeeRole.EMPLOYEE.value,
                status=status,
                password_hash=hash_password("SharedBotPass1!")
                if status == EmployeeStatus.ACTIVE.value
                else None,
            ),
        )
        await uow.commit()
        return employee


async def _bot_login(
    api_client: AsyncClient,
    *,
    token: str,
    telegram_user_id: int,
    company_id=None,
):
    body: dict[str, object] = {"telegram_user_id": telegram_user_id}
    if company_id is not None:
        body["company_id"] = str(company_id)
    return await api_client.post(
        "/api/v1/auth/bot/telegram",
        headers={"X-Bot-Service-Token": token},
        json=body,
    )


def _bearer(login_response) -> dict[str, str]:
    return {"Authorization": f"Bearer {login_response.json()['access_token']}"}


@pytest.mark.asyncio
async def test_shared_bot_resolves_company_a_and_company_b(
    api_client: AsyncClient,
    company_a,
    company_b,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "bot_company_id", "")
    tg_a = _tg_id(100_000_000)
    tg_b = _tg_id(200_000_000)
    emp_a = await _create_employee(
        company_a.id, telegram_user_id=tg_a, full_name="Employee A"
    )
    emp_b = await _create_employee(
        company_b.id, telegram_user_id=tg_b, full_name="Employee B"
    )

    login_a = await _bot_login(api_client, token=bot_service_token, telegram_user_id=tg_a)
    assert login_a.status_code == 200, login_a.text
    body_a = login_a.json()["employee"]
    assert body_a["id"] == str(emp_a.id)
    assert body_a["company_id"] == str(company_a.id)
    assert body_a["telegram_user_id"] == tg_a

    login_b = await _bot_login(api_client, token=bot_service_token, telegram_user_id=tg_b)
    assert login_b.status_code == 200, login_b.text
    body_b = login_b.json()["employee"]
    assert body_b["id"] == str(emp_b.id)
    assert body_b["company_id"] == str(company_b.id)
    assert body_b["telegram_user_id"] == tg_b
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_unknown_telegram_id_is_not_found(
    api_client: AsyncClient,
    company_a,
    bot_service_token: str,
) -> None:
    await _create_employee(company_a.id, telegram_user_id=_tg_id(100_000_000))
    response = await _bot_login(
        api_client, token=bot_service_token, telegram_user_id=_tg_id(300_000_000)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_invited_employee_is_not_authenticated(
    api_client: AsyncClient,
    company_a,
    bot_service_token: str,
) -> None:
    tg_a = _tg_id(100_000_000)
    await _create_employee(
        company_a.id,
        telegram_user_id=tg_a,
        status=EmployeeStatus.INVITED.value,
    )
    response = await _bot_login(api_client, token=bot_service_token, telegram_user_id=tg_a)
    assert response.status_code == 403
    assert "invite" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_archived_employee_is_not_authenticated(
    api_client: AsyncClient,
    company_a,
    bot_service_token: str,
) -> None:
    tg_a = _tg_id(100_000_000)
    await _create_employee(
        company_a.id,
        telegram_user_id=tg_a,
        status=EmployeeStatus.ARCHIVED.value,
    )
    response = await _bot_login(api_client, token=bot_service_token, telegram_user_id=tg_a)
    assert response.status_code == 403
    assert "archived" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_company_a_cannot_access_company_b_data_or_knowledge(
    api_client: AsyncClient,
    company_a,
    company_b,
    hr_a: Employee,
    hr_b: Employee,
    bot_service_token: str,
) -> None:
    tg_a = _tg_id(100_000_000)
    tg_b = _tg_id(200_000_000)
    emp_a = await _create_employee(
        company_a.id, telegram_user_id=tg_a, full_name="Iso A"
    )
    emp_b = await _create_employee(
        company_b.id, telegram_user_id=tg_b, full_name="Iso B"
    )

    article_b = await api_client.post(
        "/api/v1/knowledge/articles",
        headers=auth_header(hr_b),
        json={
            "company_id": str(company_b.id),
            "title": "Company B secret KB",
            "body": "COMPANY_B_KB_SECRET",
            "visibility": "company",
        },
    )
    assert article_b.status_code == 201, article_b.text
    article_b_id = article_b.json()["id"]

    login_a = await _bot_login(api_client, token=bot_service_token, telegram_user_id=tg_a)
    assert login_a.status_code == 200, login_a.text
    headers_a = _bearer(login_a)

    company_b_get = await api_client.get(
        f"/api/v1/companies/{company_b.id}",
        headers=headers_a,
    )
    assert company_b_get.status_code in {403, 404}

    emp_b_get = await api_client.get(
        f"/api/v1/employees/{emp_b.id}",
        headers=headers_a,
    )
    assert emp_b_get.status_code in {403, 404}

    article_get = await api_client.get(
        f"/api/v1/knowledge/articles/{article_b_id}",
        headers=headers_a,
    )
    assert article_get.status_code == 404

    listed_foreign = await api_client.get(
        "/api/v1/knowledge/articles",
        headers=auth_header(hr_a),
        params={"company_id": str(company_b.id)},
    )
    assert listed_foreign.status_code in {403, 404}

    login_b = await _bot_login(api_client, token=bot_service_token, telegram_user_id=tg_b)
    headers_b = _bearer(login_b)
    emp_a_from_b = await api_client.get(
        f"/api/v1/employees/{emp_a.id}",
        headers=headers_b,
    )
    assert emp_a_from_b.status_code in {403, 404}
    company_a_from_b = await api_client.get(
        f"/api/v1/companies/{company_a.id}",
        headers=headers_b,
    )
    assert company_a_from_b.status_code in {403, 404}


@pytest.mark.asyncio
async def test_request_company_id_cannot_select_or_override_tenant(
    api_client: AsyncClient,
    company_a,
    company_b,
    bot_service_token: str,
) -> None:
    tg_a = _tg_id(100_000_000)
    emp_a = await _create_employee(
        company_a.id, telegram_user_id=tg_a, full_name="No Override"
    )

    spoof = await _bot_login(
        api_client,
        token=bot_service_token,
        telegram_user_id=tg_a,
        company_id=company_b.id,
    )
    assert spoof.status_code == 200, spoof.text
    body = spoof.json()["employee"]
    assert body["id"] == str(emp_a.id)
    assert body["company_id"] == str(company_a.id)
    assert body["company_id"] != str(company_b.id)

    omitted = await _bot_login(
        api_client, token=bot_service_token, telegram_user_id=tg_a
    )
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["employee"]["company_id"] == str(company_a.id)


@pytest.mark.asyncio
async def test_invite_binds_telegram_and_web_patch_does_not_activate(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "onboardai_demo_bot")
    tg_a = _tg_id(100_000_000)
    tg_b = _tg_id(200_000_000)

    create = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "full_name": "Bind Shared",
            "email": f"bind-shared-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
            "telegram_user_id": tg_a,
        },
    )
    assert create.status_code == 201, create.text
    employee_id = create.json()["id"]
    token = create.json()["invite_url"].split("#", 1)[1]
    assert create.json()["status"] == EmployeeStatus.INVITED.value

    before = await _bot_login(api_client, token=bot_service_token, telegram_user_id=tg_a)
    assert before.status_code == 403

    patched = await api_client.patch(
        f"/api/v1/employees/{employee_id}",
        headers=auth_header(admin_a),
        json={"telegram_user_id": tg_b},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == EmployeeStatus.INVITED.value
    assert patched.json()["telegram_chat_id"] is None

    after_patch = await _bot_login(
        api_client, token=bot_service_token, telegram_user_id=tg_b
    )
    assert after_patch.status_code == 403

    bogus = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": "not-a-valid-invite-token-value",
            "telegram_user_id": tg_a,
        },
    )
    assert bogus.status_code in {400, 404}

    accept = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token,
            "telegram_user_id": tg_a,
            "telegram_username": "shared_bot",
            "telegram_chat_id": tg_a,
            "company_id": str(uuid4()),
        },
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["employee"]["status"] == EmployeeStatus.ACTIVE.value
    assert accept.json()["employee"]["telegram_user_id"] == tg_a
    assert accept.json()["employee"]["company_id"] == str(company_a.id)

    found = await _bot_login(api_client, token=bot_service_token, telegram_user_id=tg_a)
    assert found.status_code == 200, found.text
    assert found.json()["employee"]["id"] == employee_id
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_bot_jwt_profile_company_and_assignments(
    api_client: AsyncClient,
    company_a,
    bot_service_token: str,
) -> None:
    tg_a = _tg_id(100_000_000)
    employee = await _create_employee(
        company_a.id, telegram_user_id=tg_a, full_name="Cabinet User"
    )
    login = await _bot_login(api_client, token=bot_service_token, telegram_user_id=tg_a)
    assert login.status_code == 200, login.text
    headers = _bearer(login)

    me = await api_client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["id"] == str(employee.id)
    assert me.json()["company_id"] == str(company_a.id)
    assert me.json().get("company_name")

    assignments = await api_client.get(
        f"/api/v1/employees/{employee.id}/assignments",
        headers=headers,
    )
    assert assignments.status_code == 200, assignments.text
