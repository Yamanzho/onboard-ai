"""AI-11A: employee-owned conversation ACL. Not a KB authorization service."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.db.enums import EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.conversations import ConversationService
from tests.conftest import _create_employee, _uow_factory
from tests.security.test_rls_adversarial import _set_tenant


@pytest.fixture
def conversations() -> ConversationService:
    return ConversationService(uow_factory=_uow_factory)


@pytest.fixture
async def app_role_session() -> AsyncSession:
    settings = get_settings()
    url = settings.database_url
    if "onboard_app" not in url and "onboard_owner" in url:
        url = url.replace("onboard_owner", "onboard_app")
    engine = create_async_engine(url, echo=False, connect_args={"ssl": False})
    async_session = async_sessionmaker(engine, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_employee_can_create_and_read_own_conversation(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    created = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    loaded = await conversations.get_conversation(
        employee_a.company_id, employee_a.id, created.id
    )
    assert loaded.id == created.id
    assert loaded.employee_id == employee_a.id
    assert loaded.company_id == employee_a.company_id


@pytest.mark.asyncio
async def test_employee_cannot_read_or_write_another_employee_conversation(
    conversations: ConversationService,
    employee_a: Employee,
    company_a: Company,
) -> None:
    peer = await _create_employee(
        company_id=company_a.id, role=EmployeeRole.EMPLOYEE.value
    )
    other = await conversations.create_conversation(company_a.id, peer.id)
    await conversations.add_message(
        company_a.id, peer.id, other.id, "user", "peer secret"
    )
    with pytest.raises(NotFoundError):
        await conversations.get_conversation(
            employee_a.company_id, employee_a.id, other.id
        )
    with pytest.raises(NotFoundError):
        await conversations.add_message(
            employee_a.company_id,
            employee_a.id,
            other.id,
            "user",
            "hijack",
        )
    with pytest.raises(NotFoundError):
        await conversations.list_messages(
            employee_a.company_id, employee_a.id, other.id
        )


@pytest.mark.asyncio
async def test_hr_and_admin_do_not_receive_employee_conversations(
    conversations: ConversationService,
    employee_a: Employee,
    hr_a: Employee,
    admin_a: Employee,
) -> None:
    created = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    await conversations.add_message(
        employee_a.company_id,
        employee_a.id,
        created.id,
        "user",
        "employee private chat",
    )
    for actor in (hr_a, admin_a):
        with pytest.raises(NotFoundError):
            await conversations.get_conversation(actor.company_id, actor.id, created.id)
        with pytest.raises(NotFoundError):
            await conversations.add_message(
                actor.company_id, actor.id, created.id, "user", "staff hijack"
            )
        listed = await conversations.list_conversations(actor.company_id, actor.id)
        assert created.id not in {row.id for row in listed}


@pytest.mark.asyncio
async def test_employee_cannot_read_or_write_another_company_conversation(
    conversations: ConversationService,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    foreign = await conversations.create_conversation(
        employee_b.company_id, employee_b.id
    )
    message = await conversations.add_message(
        employee_b.company_id,
        employee_b.id,
        foreign.id,
        "assistant",
        "company B secret answer",
    )
    with pytest.raises(NotFoundError):
        await conversations.get_conversation(
            employee_a.company_id, employee_a.id, foreign.id
        )
    with pytest.raises(NotFoundError):
        await conversations.add_message(
            employee_a.company_id,
            employee_a.id,
            foreign.id,
            "user",
            "cross-company write",
        )
    with pytest.raises(NotFoundError):
        await conversations.get_message(
            employee_a.company_id, employee_a.id, message.id
        )


@pytest.mark.asyncio
async def test_uuid_probing_is_not_found(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    with pytest.raises(NotFoundError, match="Conversation not found"):
        await conversations.get_conversation(
            employee_a.company_id, employee_a.id, uuid4()
        )
    with pytest.raises(NotFoundError, match="Message not found"):
        await conversations.get_message(
            employee_a.company_id, employee_a.id, uuid4()
        )


@pytest.mark.asyncio
async def test_company_and_employee_spoofing_cannot_change_owner(
    conversations: ConversationService,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    with pytest.raises(NotFoundError):
        await conversations.create_conversation(
            employee_b.company_id, employee_a.id
        )
    with pytest.raises(NotFoundError):
        await conversations.create_conversation(
            employee_a.company_id, employee_b.id
        )
    own = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    with pytest.raises(NotFoundError):
        await conversations.get_conversation(
            employee_b.company_id, employee_a.id, own.id
        )
    with pytest.raises(NotFoundError):
        await conversations.get_conversation(
            employee_a.company_id, employee_b.id, own.id
        )


@pytest.mark.asyncio
async def test_conversation_id_alone_is_never_authorization(
    conversations: ConversationService,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    owned = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    with pytest.raises(NotFoundError):
        await conversations.get_conversation(
            employee_b.company_id, employee_b.id, owned.id
        )


@pytest.mark.asyncio
async def test_message_id_probing_cannot_expose_another_conversation(
    conversations: ConversationService,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    owned = await conversations.create_conversation(
        employee_b.company_id, employee_b.id
    )
    hidden = await conversations.add_message(
        employee_b.company_id,
        employee_b.id,
        owned.id,
        "user",
        "hidden-from-a",
    )
    with pytest.raises(NotFoundError, match="Message not found"):
        await conversations.get_message(
            employee_a.company_id, employee_a.id, hidden.id
        )


@pytest.mark.asyncio
async def test_archived_conversation_rejects_writes_and_remains_readable(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    created = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    await conversations.add_message(
        employee_a.company_id,
        employee_a.id,
        created.id,
        "user",
        "before archive",
    )
    archived = await conversations.archive_conversation(
        employee_a.company_id, employee_a.id, created.id
    )
    assert archived.status == "archived"
    readable = await conversations.get_conversation(
        employee_a.company_id, employee_a.id, created.id
    )
    assert readable.id == created.id
    with pytest.raises(ValidationError, match="archived"):
        await conversations.add_message(
            employee_a.company_id,
            employee_a.id,
            created.id,
            "assistant",
            "after archive",
        )


@pytest.mark.asyncio
async def test_message_content_is_not_logged(
    conversations: ConversationService,
    employee_a: Employee,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = f"CONVERSATION_LOG_SECRET_{uuid4().hex}"
    with caplog.at_level("INFO"):
        created = await conversations.create_conversation(
            employee_a.company_id, employee_a.id, title=f"title-{secret}"
        )
        await conversations.add_message(
            employee_a.company_id,
            employee_a.id,
            created.id,
            "user",
            secret,
        )
        await conversations.add_message(
            employee_a.company_id,
            employee_a.id,
            created.id,
            "assistant",
            f"answer-{secret}",
        )
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert secret not in combined
    assert str(created.id) in combined
    assert str(employee_a.company_id) in combined
    assert str(employee_a.id) in combined


@pytest.mark.asyncio
async def test_rls_tenant_a_cannot_select_insert_update_delete_b(
    conversations: ConversationService,
    employee_b: Employee,
    company_a: Company,
    company_b: Company,
    app_role_session: AsyncSession,
) -> None:
    foreign = await conversations.create_conversation(
        employee_b.company_id, employee_b.id
    )
    foreign_msg = await conversations.add_message(
        employee_b.company_id,
        employee_b.id,
        foreign.id,
        "user",
        "B conversation secret",
    )

    await _set_tenant(app_role_session, company_a.id)
    probed = (
        await app_role_session.execute(
            text("SELECT id FROM ai_conversations WHERE id = :id"),
            {"id": foreign.id},
        )
    ).first()
    assert probed is None
    probed_msg = (
        await app_role_session.execute(
            text("SELECT content FROM ai_messages WHERE id = :id"),
            {"id": foreign_msg.id},
        )
    ).first()
    assert probed_msg is None

    with pytest.raises(Exception):
        await app_role_session.execute(
            text(
                """
                INSERT INTO ai_conversations
                    (id, company_id, employee_id, status, created_at, updated_at)
                VALUES
                    (:id, :cid, :eid, 'active', now(), now())
                """
            ),
            {
                "id": uuid4(),
                "cid": company_b.id,
                "eid": employee_b.id,
            },
        )
    await app_role_session.rollback()

    await _set_tenant(app_role_session, company_a.id)
    updated = await app_role_session.execute(
        text("UPDATE ai_conversations SET title = 'hijacked' WHERE id = :id"),
        {"id": foreign.id},
    )
    assert updated.rowcount == 0
    await app_role_session.commit()

    deleted = await app_role_session.execute(
        text("DELETE FROM ai_conversations WHERE id = :id"),
        {"id": foreign.id},
    )
    assert deleted.rowcount == 0
    await app_role_session.commit()

    deleted_msg = await app_role_session.execute(
        text("DELETE FROM ai_messages WHERE id = :id"),
        {"id": foreign_msg.id},
    )
    assert deleted_msg.rowcount == 0
    await app_role_session.commit()

    remaining = await conversations.get_conversation(
        employee_b.company_id, employee_b.id, foreign.id
    )
    assert remaining.id == foreign.id
    rows = await conversations.list_messages(
        employee_b.company_id, employee_b.id, foreign.id
    )
    assert [row.content for row in rows] == ["B conversation secret"]


def test_conversation_service_is_not_kb_acl() -> None:
    from pathlib import Path

    src = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "services"
        / "ai"
        / "conversations.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "from app.services.knowledge",
        "from app.services.ai.retriever",
        "from app.services.ai.prompts",
        "from app.services.ai.chat",
        "list_articles",
        "AIACLService",
        "VectorACL",
        "actor_role",
        "EmployeeRole.HR",
        "EmployeeRole.ADMIN",
        "SUPER_ADMIN",
        "openai.com",
        "build_user_prompt",
    ):
        assert forbidden not in src
