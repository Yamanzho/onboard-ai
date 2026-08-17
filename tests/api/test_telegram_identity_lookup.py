"""Telegram identity lookup: FOUND / NOT_FOUND / invited / shared bot.

Does not change RAG. Proves bot login is telegram_user_id → Employee →
employee.company_id, plus status gates. BOT_COMPANY_ID is not an identity scope.
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
    token = "test-bot-identity-service-token-32c"
    monkeypatch.setenv("BOT_SERVICE_TOKEN", token)
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", token)
    settings.bot_login_rate_limit = 0
    return token


def _bind_bot_company(monkeypatch: pytest.MonkeyPatch, company_id) -> None:
    monkeypatch.setenv("BOT_COMPANY_ID", str(company_id))
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_company_id", str(company_id))
    settings.bot_login_rate_limit = 0


async def _create_active(
    company_id,
    *,
    telegram_user_id: int,
    full_name: str = "Identity Active",
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=telegram_user_id,
                full_name=full_name,
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ACTIVE.value,
                password_hash=hash_password("IdentityPass1!"),
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


@pytest.mark.asyncio
async def test_matching_telegram_user_id_on_active_employee_is_found(
    api_client: AsyncClient,
    company_a,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_id = _tg_id(400_000_000)
    _bind_bot_company(monkeypatch, company_a.id)
    employee = await _create_active(company_a.id, telegram_user_id=test_id)

    response = await _bot_login(
        api_client,
        token=bot_service_token,
        company_id=company_a.id,
        telegram_user_id=test_id,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["employee"]["id"] == str(employee.id)
    assert body["employee"]["telegram_user_id"] == test_id
    assert body["employee"]["company_id"] == str(company_a.id)
    assert body["employee"]["status"] == EmployeeStatus.ACTIVE.value
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_different_telegram_user_id_is_not_found(
    api_client: AsyncClient,
    company_a,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bind_bot_company(monkeypatch, company_a.id)
    await _create_active(company_a.id, telegram_user_id=_tg_id(400_000_000))

    response = await _bot_login(
        api_client,
        token=bot_service_token,
        company_id=company_a.id,
        telegram_user_id=_tg_id(500_000_000),
    )
    assert response.status_code == 404
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_cross_company_telegram_id_is_found_for_shared_bot(
    api_client: AsyncClient,
    company_a,
    company_b,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Employee lives in company B; BOT_COMPANY_ID is company A → still FOUND."""
    test_id = _tg_id(400_000_000)
    _bind_bot_company(monkeypatch, company_a.id)
    employee = await _create_active(
        company_b.id,
        telegram_user_id=test_id,
        full_name="Foreign Identity",
    )

    found = await _bot_login(
        api_client,
        token=bot_service_token,
        telegram_user_id=test_id,
    )
    assert found.status_code == 200, found.text
    assert found.json()["employee"]["id"] == str(employee.id)
    assert found.json()["employee"]["company_id"] == str(company_b.id)

    spoof_body = await _bot_login(
        api_client,
        token=bot_service_token,
        company_id=company_a.id,
        telegram_user_id=test_id,
    )
    assert spoof_body.status_code == 200, spoof_body.text
    assert spoof_body.json()["employee"]["company_id"] == str(company_b.id)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_web_assigned_telegram_id_on_invited_employee_cannot_bot_login(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Web create/PATCH of telegram_user_id is not Telegram binding.

    Tenant API can persist the numeric id, but status stays invited and
    bot login rejects invited employees (403, not 200).
    """
    monkeypatch.setenv("SMTP_HOST", "")
    _bind_bot_company(monkeypatch, company_a.id)
    test_id = _tg_id(400_000_000)
    other_id = _tg_id(500_000_000)

    create = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "full_name": "Web Assigned TG",
            "email": f"web-tg-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
            "telegram_user_id": test_id,
        },
    )
    assert create.status_code == 201, create.text
    employee_id = create.json()["id"]
    assert create.json()["telegram_user_id"] == test_id
    assert create.json()["status"] == EmployeeStatus.INVITED.value
    assert create.json()["telegram_chat_id"] is None

    login_matching = await _bot_login(
        api_client,
        token=bot_service_token,
        company_id=company_a.id,
        telegram_user_id=test_id,
    )
    assert login_matching.status_code == 403
    assert "invite" in login_matching.json()["detail"].lower()

    patched = await api_client.patch(
        f"/api/v1/employees/{employee_id}",
        headers=auth_header(admin_a),
        json={"telegram_user_id": other_id},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["telegram_user_id"] == other_id
    assert patched.json()["status"] == EmployeeStatus.INVITED.value
    assert patched.json()["telegram_chat_id"] is None

    login_patched = await _bot_login(
        api_client,
        token=bot_service_token,
        company_id=company_a.id,
        telegram_user_id=other_id,
    )
    assert login_patched.status_code == 403

    login_old = await _bot_login(
        api_client,
        token=bot_service_token,
        company_id=company_a.id,
        telegram_user_id=test_id,
    )
    assert login_old.status_code == 404
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_telegram_start_invite_bind_then_matching_id_is_found(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    bot_service_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "onboardai_demo_bot")
    _bind_bot_company(monkeypatch, company_a.id)
    test_id = _tg_id(400_000_000)

    create = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(admin_a),
        json={
            "company_id": str(company_a.id),
            "full_name": "Bind Then Login",
            "email": f"bind-login-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert create.status_code == 201, create.text
    token = create.json()["invite_url"].split("#", 1)[1]
    placeholder_id = create.json()["telegram_user_id"]
    assert placeholder_id != test_id

    accept = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": bot_service_token},
        json={
            "token": token,
            "telegram_user_id": test_id,
            "telegram_username": "identity_debug",
            "telegram_chat_id": test_id,
            "company_id": str(company_a.id),
        },
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["employee"]["status"] == EmployeeStatus.ACTIVE.value
    assert accept.json()["employee"]["telegram_user_id"] == test_id

    login = await _bot_login(
        api_client,
        token=bot_service_token,
        company_id=company_a.id,
        telegram_user_id=test_id,
    )
    assert login.status_code == 200, login.text
    assert login.json()["employee"]["telegram_user_id"] == test_id
    get_settings.cache_clear()


def test_bot_client_login_payload_omits_company_id() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "app" / "bot" / "api" / "client.py").read_text(
        encoding="utf-8"
    )
    fn = src.split("async def authenticate_telegram", 1)[1].split("async def ", 1)[0]
    assert '"telegram_user_id": telegram_user_id' in fn
    assert '"company_id"' not in fn
    invite_fn = src.split("async def accept_invite_via_telegram", 1)[1].split(
        "async def ", 1
    )[0]
    assert '"telegram_user_id": telegram_user_id' in invite_fn
    assert '"company_id"' not in invite_fn
