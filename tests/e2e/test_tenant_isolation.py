"""Cross-tenant isolation: Company A must not read or mutate Company B.

Covers API authorization (404/403) and PostgreSQL RLS for conversations,
which have no public HTTP API yet.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.enums import AIMessageRole, ConversationStatus, EmployeeRole, EmployeeStatus
from app.db.models.ai_conversation import AIConversation
from app.db.models.ai_message import AIMessage
from app.db.models.company import Company
from app.db.models.employee import Employee
from tests.conftest import _uow_factory, auth_header
from tests.security.test_rls_adversarial import _set_tenant

_BOT_SERVICE_TOKEN = "ci-isolation-bot-service-token-32chars"


@pytest.fixture
async def app_role_session() -> AsyncIterator[AsyncSession]:
    """Session connected as onboard_app (RLS enforced, no BYPASSRLS)."""
    settings = get_settings()
    url = settings.database_url
    if "onboard_app" not in url and "onboard_owner" in url:
        url = url.replace("onboard_owner", "onboard_app")
    engine = create_async_engine(url, echo=False, connect_args={"ssl": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _invite_token(invite_url: str | None) -> str:
    assert invite_url and "/invite#" in invite_url
    return invite_url.split("#", 1)[1]


def _bind_bot_company(monkeypatch: pytest.MonkeyPatch, company_id) -> None:
    monkeypatch.setenv("BOT_SERVICE_TOKEN", _BOT_SERVICE_TOKEN)
    monkeypatch.setenv("BOT_COMPANY_ID", str(company_id))
    monkeypatch.setenv("SMTP_HOST", "")
    get_settings.cache_clear()
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_service_token", _BOT_SERVICE_TOKEN)
    monkeypatch.setattr(settings, "bot_company_id", str(company_id))
    settings.bot_login_rate_limit = 0


@pytest.mark.asyncio
async def test_tenant_a_cannot_access_tenant_b_resources(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    admin_a: Employee,
    admin_b: Employee,
    hr_a: Employee,
    hr_b: Employee,
    employee_a: Employee,
    employee_b: Employee,
    monkeypatch: pytest.MonkeyPatch,
    app_role_session,
) -> None:
    headers_a = auth_header(admin_a)
    headers_hr_a = auth_header(hr_a)
    headers_emp_a = auth_header(employee_a)
    headers_hr_b = auth_header(hr_b)

    article_b = await api_client.post(
        "/api/v1/knowledge/articles",
        headers=headers_hr_b,
        json={
            "company_id": str(company_b.id),
            "title": "B handbook",
            "body": "COMPANY_B_KB_SECRET",
            "visibility": "company",
        },
    )
    assert article_b.status_code == 201, article_b.text
    article_b_id = article_b.json()["id"]
    publish_article = await api_client.post(
        f"/api/v1/knowledge/articles/{article_b_id}/publish",
        headers=headers_hr_b,
    )
    assert publish_article.status_code == 200, publish_article.text

    program_b = await api_client.post(
        "/api/v1/programs",
        headers=headers_hr_b,
        json={"company_id": str(company_b.id), "title": "B onboarding"},
    )
    assert program_b.status_code == 201, program_b.text
    program_b_id = program_b.json()["id"]
    step_b = await api_client.post(
        f"/api/v1/programs/{program_b_id}/steps",
        headers=headers_hr_b,
        json={"title": "B step", "step_type": "content", "content": {"body": "B"}},
    )
    assert step_b.status_code == 201, step_b.text
    publish_b = await api_client.post(
        f"/api/v1/programs/{program_b_id}/publish",
        headers=headers_hr_b,
    )
    assert publish_b.status_code == 200, publish_b.text

    assign_b = await api_client.post(
        "/api/v1/assignments",
        headers=headers_hr_b,
        json={
            "employee_id": str(employee_b.id),
            "program_id": program_b_id,
        },
    )
    assert assign_b.status_code == 201, assign_b.text
    assignment_b_id = assign_b.json()["id"]

    invited_b = await api_client.post(
        "/api/v1/employees",
        headers=headers_hr_b,
        json={
            "company_id": str(company_b.id),
            "full_name": "Invited B",
            "email": f"invited-b-{uuid4().hex[:8]}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert invited_b.status_code == 201, invited_b.text
    invited_b_id = invited_b.json()["id"]
    invited_b_token = _invite_token(invited_b.json().get("invite_url"))

    async with _uow_factory() as uow:
        await uow.enter_platform()
        conversation = await uow.ai_conversations.create(
            AIConversation(
                company_id=company_b.id,
                employee_id=employee_b.id,
                status=ConversationStatus.ACTIVE.value,
            ),
        )
        await uow.ai_messages.create(
            AIMessage(
                conversation_id=conversation.id,
                company_id=company_b.id,
                role=AIMessageRole.USER.value,
                content="COMPANY_B_CHAT_SECRET",
            ),
        )
        await uow.commit()
        conversation_id = conversation.id

    # --- API: User A must not read Company B ---
    kb = await api_client.get(
        f"/api/v1/knowledge/articles/{article_b_id}",
        headers=headers_emp_a,
    )
    assert kb.status_code == 404, kb.text
    assert "COMPANY_B_KB_SECRET" not in kb.text

    kb_list = await api_client.get(
        "/api/v1/knowledge/articles",
        headers=headers_hr_a,
        params={"company_id": str(company_b.id)},
    )
    assert kb_list.status_code in {400, 404}, kb_list.text

    program = await api_client.get(
        f"/api/v1/programs/{program_b_id}",
        headers=headers_hr_a,
    )
    assert program.status_code == 404, program.text

    employees = await api_client.get(
        "/api/v1/employees",
        headers=headers_hr_a,
        params={"company_id": str(company_b.id)},
    )
    assert employees.status_code == 404, employees.text

    other_employee = await api_client.get(
        f"/api/v1/employees/{employee_b.id}",
        headers=headers_hr_a,
    )
    assert other_employee.status_code == 404, other_employee.text

    assignment = await api_client.get(
        f"/api/v1/assignments/{assignment_b_id}",
        headers=headers_hr_a,
    )
    assert assignment.status_code == 404, assignment.text

    # --- API: User A must not mutate Company B ---
    patch_company = await api_client.patch(
        f"/api/v1/companies/{company_b.id}",
        headers=headers_a,
        json={"name": "Hijacked B"},
    )
    assert patch_company.status_code == 404, patch_company.text

    patch_employee = await api_client.patch(
        f"/api/v1/employees/{employee_b.id}",
        headers=headers_hr_a,
        json={"full_name": "Hijacked employee"},
    )
    assert patch_employee.status_code == 404, patch_employee.text

    patch_program = await api_client.patch(
        f"/api/v1/programs/{program_b_id}",
        headers=headers_hr_a,
        json={"title": "Hijacked program"},
    )
    assert patch_program.status_code == 404, patch_program.text

    # --- Invites / Telegram binding of Company B ---
    resend = await api_client.post(
        f"/api/v1/employees/{invited_b_id}/resend-invite",
        headers=headers_hr_a,
    )
    assert resend.status_code == 404, resend.text

    _bind_bot_company(monkeypatch, company_a.id)
    steal_bind = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": _BOT_SERVICE_TOKEN},
        json={
            "token": invited_b_token,
            "telegram_user_id": 9_300_000_042,
            "company_id": str(company_b.id),
        },
    )
    assert steal_bind.status_code == 403, steal_bind.text

    steal_bind_as_a = await api_client.post(
        "/api/v1/auth/bot/invite/accept",
        headers={"X-Bot-Service-Token": _BOT_SERVICE_TOKEN},
        json={
            "token": invited_b_token,
            "telegram_user_id": 9_300_000_043,
            "company_id": str(company_a.id),
        },
    )
    assert steal_bind_as_a.status_code in {400, 403, 404}, steal_bind_as_a.text

    async with _uow_factory() as uow:
        await uow.enter_platform()
        still_invited = await uow.employees.get_by_id(invited_b_id)
        assert still_invited is not None
        assert still_invited.status == EmployeeStatus.INVITED.value
        assert still_invited.role == EmployeeRole.EMPLOYEE.value

    # --- RLS: conversations of B are invisible to tenant A ---
    await _set_tenant(app_role_session, company_a.id)
    visible = (
        await app_role_session.execute(
            text("SELECT id FROM ai_conversations WHERE id = :id"),
            {"id": conversation_id},
        )
    ).first()
    assert visible is None

    leaked = (
        await app_role_session.execute(
            text("SELECT id FROM ai_conversations WHERE company_id = :cid"),
            {"cid": company_b.id},
        )
    ).first()
    assert leaked is None

    leaked_msg = (
        await app_role_session.execute(
            text("SELECT content FROM ai_messages WHERE conversation_id = :id"),
            {"id": conversation_id},
        )
    ).first()
    assert leaked_msg is None
