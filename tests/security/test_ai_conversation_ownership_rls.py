"""Phase 7G: PostgreSQL enforces employee ownership of AI history."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.enums import AIMessageRole, EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.rls_guard import SESSION_RLS_MODE_KEY
from app.db.uow import RlsMode
from app.repositories.ai_conversation import AIConversationRepository
from app.services.ai.conversations import ConversationService
from tests.conftest import _create_employee, _uow_factory


@pytest.fixture
def conversations() -> ConversationService:
    return ConversationService(uow_factory=_uow_factory)


@pytest.fixture
async def app_role_session() -> AsyncIterator[AsyncSession]:
    settings = get_settings()
    url = settings.database_url
    if "onboard_app" not in url and "onboard_owner" in url:
        url = url.replace("onboard_owner", "onboard_app")
    engine = create_async_engine(url, echo=False, connect_args={"ssl": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _set_employee(session: AsyncSession, employee: Employee) -> None:
    session.info[SESSION_RLS_MODE_KEY] = RlsMode.TENANT
    values = {
        "app.current_company_id": str(employee.company_id),
        "app.current_employee_id": str(employee.id),
        "app.platform_admin": "",
        "app.auth_mode": "",
        "app.session_mode": "",
        "app.auth_employee_id": "",
        "app.auth_telegram_user_id": "",
        "app.auth_invite_token_hash": "",
        "app.auth_super_admin_id": "",
        "app.auth_super_admin_email": "",
    }
    for key, value in values.items():
        await session.execute(
            text("SELECT set_config(:key, :value, true)"),
            {"key": key, "value": value},
        )


@pytest.mark.asyncio
async def test_uow_derives_employee_tenant_and_platform_cannot_read_ai_history(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    own = await conversations.create_conversation(
        employee_a.company_id,
        employee_a.id,
    )

    async with _uow_factory() as uow:
        await uow.enter_tenant(employee_a.company_id)
        assert await uow.ai_conversations.get_by_id(own.id) is None

        resolved = await uow.enter_employee(employee_a.id)
        assert resolved.id == employee_a.id
        context = (
            await uow.session.execute(
                text("SELECT app.company_id(), app.employee_id()")
            )
        ).one()
        assert context == (employee_a.company_id, employee_a.id)
        assert await uow.ai_conversations.get_by_id(own.id) is not None

        await uow.enter_platform()
        cleared = (
            await uow.session.execute(
                text("SELECT app.company_id(), app.employee_id()")
            )
        ).one()
        assert cleared == (None, None)
        assert await uow.ai_conversations.get_by_id(own.id) is None


@pytest.mark.asyncio
async def test_same_company_owner_rls_blocks_unscoped_repository_and_raw_sql(
    conversations: ConversationService,
    company_a: Company,
    employee_a: Employee,
    app_role_session: AsyncSession,
) -> None:
    peer = await _create_employee(
        company_id=company_a.id,
        role=EmployeeRole.EMPLOYEE.value,
    )
    own = await conversations.create_conversation(company_a.id, employee_a.id)
    peer_conversation = await conversations.create_conversation(company_a.id, peer.id)
    peer_message = await conversations.add_message(
        company_a.id,
        peer.id,
        peer_conversation.id,
        AIMessageRole.USER.value,
        "peer private message",
    )

    await _set_employee(app_role_session, employee_a)
    repository = AIConversationRepository(app_role_session)
    assert await repository.get_by_id(own.id) is not None
    assert await repository.get_by_id(peer_conversation.id) is None
    listed = await repository.list()
    assert own.id in {row.id for row in listed}
    assert peer_conversation.id not in {row.id for row in listed}

    assert (
        await app_role_session.execute(
            text("SELECT id FROM ai_conversations WHERE id = :id"),
            {"id": peer_conversation.id},
        )
    ).first() is None
    assert (
        await app_role_session.execute(
            text("SELECT id FROM ai_messages WHERE id = :id"),
            {"id": peer_message.id},
        )
    ).first() is None

    with pytest.raises(DBAPIError):
        await app_role_session.execute(
            text(
                """
                INSERT INTO ai_conversations
                    (id, company_id, employee_id, status, created_at, updated_at)
                VALUES (:id, :company_id, :employee_id, 'active', now(), now())
                """
            ),
            {
                "id": uuid4(),
                "company_id": company_a.id,
                "employee_id": peer.id,
            },
        )
    await app_role_session.rollback()

    await _set_employee(app_role_session, employee_a)
    with pytest.raises(DBAPIError):
        await app_role_session.execute(
            text(
                """
                INSERT INTO ai_messages
                    (id, conversation_id, company_id, role, content, created_at, updated_at)
                VALUES (:id, :conversation_id, :company_id, 'user', 'hijack', now(), now())
                """
            ),
            {
                "id": uuid4(),
                "conversation_id": peer_conversation.id,
                "company_id": company_a.id,
            },
        )
    await app_role_session.rollback()

    await _set_employee(app_role_session, employee_a)
    with pytest.raises(DBAPIError):
        await app_role_session.execute(
            text(
                "UPDATE ai_conversations SET employee_id = :peer_id "
                "WHERE id = :conversation_id"
            ),
            {"peer_id": peer.id, "conversation_id": own.id},
        )
    await app_role_session.rollback()

    await _set_employee(app_role_session, employee_a)
    updated = await app_role_session.execute(
        text("UPDATE ai_conversations SET title = 'hijacked' WHERE id = :id"),
        {"id": peer_conversation.id},
    )
    assert updated.rowcount == 0
    deleted = await app_role_session.execute(
        text("DELETE FROM ai_conversations WHERE id = :id"),
        {"id": peer_conversation.id},
    )
    assert deleted.rowcount == 0
    await app_role_session.commit()

    assert (
        await conversations.get_conversation(company_a.id, peer.id, peer_conversation.id)
    ).id == peer_conversation.id


@pytest.mark.asyncio
async def test_hr_admin_and_reused_connection_remain_employee_scoped(
    conversations: ConversationService,
    employee_a: Employee,
    hr_a: Employee,
    admin_a: Employee,
    app_role_session: AsyncSession,
) -> None:
    employee_conversation = await conversations.create_conversation(
        employee_a.company_id,
        employee_a.id,
    )
    hr_conversation = await conversations.create_conversation(hr_a.company_id, hr_a.id)

    for actor in (hr_a, admin_a):
        await _set_employee(app_role_session, actor)
        assert (
            await app_role_session.execute(
                text("SELECT id FROM ai_conversations WHERE id = :id"),
                {"id": employee_conversation.id},
            )
        ).first() is None
        await app_role_session.rollback()

    # Reuse one connection: rollback clears A's LOCAL employee context.
    await _set_employee(app_role_session, employee_a)
    assert (
        await app_role_session.execute(
            text("SELECT id FROM ai_conversations WHERE id = :id"),
            {"id": employee_conversation.id},
        )
    ).first() is not None
    await app_role_session.rollback()
    assert (
        await app_role_session.execute(text("SELECT id FROM ai_conversations"))
    ).all() == []

    await _set_employee(app_role_session, hr_a)
    visible = (
        await app_role_session.execute(text("SELECT id FROM ai_conversations"))
    ).scalars()
    assert set(visible) == {hr_conversation.id}
    await app_role_session.rollback()


@pytest.mark.asyncio
async def test_forged_company_and_role_claims_do_not_change_ai_owner(
    api_client: AsyncClient,
    conversations: ConversationService,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    peer = await _create_employee(
        company_id=company_a.id,
        role=EmployeeRole.EMPLOYEE.value,
    )
    own = await conversations.create_conversation(company_a.id, employee_a.id)
    peer_conversation = await conversations.create_conversation(company_a.id, peer.id)
    forged = create_access_token(
        subject=employee_a.id,
        role=EmployeeRole.ADMIN.value,
        company_id=company_b.id,
    )
    headers = {"Authorization": f"Bearer {forged}"}

    own_response = await api_client.get(
        f"/api/v1/ai/conversations/{own.id}",
        headers=headers,
    )
    assert own_response.status_code == 200, own_response.text
    peer_response = await api_client.get(
        f"/api/v1/ai/conversations/{peer_conversation.id}",
        headers=headers,
    )
    assert peer_response.status_code == 404


def test_phase7g_migration_is_policy_focused_and_reversible() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    migration = (
        root
        / "alembic"
        / "versions"
        / "e3f4a5b6c7d8_ai_conversation_ownership_rls.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"' in migration
    assert "app.current_employee_id" in migration
    assert 'CREATE POLICY employee_ownership ON "ai_conversations"' in migration
    assert 'CREATE POLICY employee_ownership ON "ai_messages"' in migration
    assert "EXISTS (" in migration
    assert "ALTER TABLE" in migration and "FORCE ROW LEVEL SECURITY" in migration
    downgrade = migration.split("def downgrade()", 1)[1]
    assert "CREATE POLICY tenant_isolation" in downgrade
    assert "DROP FUNCTION IF EXISTS app.employee_id()" in downgrade
