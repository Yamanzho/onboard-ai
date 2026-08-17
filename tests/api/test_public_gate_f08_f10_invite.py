"""F-08 / F-10 / invite transport regression for public-production gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.security import hash_token
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from app.db.models.employee_invite import EmployeeInvite
from tests.conftest import _uow_factory

pytestmark = pytest.mark.security

ROOT = Path(__file__).resolve().parents[2]


def test_get_session_removed_from_db_session_module() -> None:
    """F-10: no generic session dependency that can skip RLS enter_*."""
    import app.db.session as session_mod

    assert not hasattr(session_mod, "get_session")
    source = (ROOT / "app" / "db" / "session.py").read_text(encoding="utf-8")
    assert "async def get_session" not in source
    assert "F-10" in source


def test_bot_company_id_documented_as_optional_shared_bot_metadata() -> None:
    deployment = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "BOT_COMPANY_ID" in deployment
    lowered = deployment.lower()
    assert "shared" in lowered or "one telegram bot" in lowered or "one bot" in lowered


@pytest.mark.asyncio
async def test_bot_login_ignores_body_company_id(
    api_client: AsyncClient,
    company_a,
    company_b,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F-08: body company_id cannot authorize or switch tenant."""
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", "test-bot-service-token-32chars!!")
    monkeypatch.setattr(settings, "bot_company_id", str(company_b.id))

    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                full_name="Bot User",
                email=f"bot-{uuid4().hex[:8]}@example.com",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ACTIVE.value,
                telegram_user_id=9_100_001,
            )
        )
        await uow.commit()

    ok = await api_client.post(
        "/api/v1/auth/bot/telegram",
        json={"telegram_user_id": 9_100_001},
        headers={"X-Bot-Service-Token": "test-bot-service-token-32chars!!"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["employee"]["id"] == str(employee.id)
    assert ok.json()["employee"]["company_id"] == str(company_a.id)

    spoof = await api_client.post(
        "/api/v1/auth/bot/telegram",
        json={"company_id": str(company_b.id), "telegram_user_id": 9_100_001},
        headers={"X-Bot-Service-Token": "test-bot-service-token-32chars!!"},
    )
    assert spoof.status_code == 200, spoof.text
    assert spoof.json()["employee"]["company_id"] == str(company_a.id)


@pytest.mark.asyncio
async def test_invite_preview_uses_body_not_path(
    api_client: AsyncClient,
    company_a,
) -> None:
    """Invite secret must not be required in the URL path for preview."""
    email = f"inv-{uuid4().hex[:8]}@example.com"
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                full_name="Invite Preview",
                email=email,
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.INVITED.value,
                telegram_user_id=uuid4().int % 1_000_000_000 + 8000,
            )
        )
        await uow.commit()
        employee_id = employee.id

    raw = f"preview-token-{uuid4().hex}"
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_a.id,
                employee_id=employee_id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
                invited_email=email,
                purpose='employee',
            )
        )
        await uow.commit()

    path_get = await api_client.get(f"/api/v1/auth/invite/{raw}")
    assert path_get.status_code == 404

    preview = await api_client.post(
        "/api/v1/auth/invite/preview",
        json={"token": raw},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["employee_id"] == str(employee_id)

    async with _uow_factory() as uow:
        await uow.enter_auth_bootstrap(invite_token_hash=hash_token(raw))
        row = await uow.employee_invites.get_by_token_hash(hash_token(raw))
        assert row is not None
        assert row.token_hash == hash_token(raw)
        assert raw not in row.token_hash


def test_invite_email_url_uses_fragment_not_path() -> None:
    source = (ROOT / "app" / "services" / "platform_management.py").read_text(encoding="utf-8")
    assert "/invite#{token}" in source
    assert "/invite/{token}" not in source
