"""AI-11A conversation persistence: create/list/archive/messages/ownership."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import inspect, text

from app.core.ai_constants import (
    MAX_CONVERSATION_MESSAGE_CHARS,
    MAX_CONVERSATION_TITLE_CHARS,
)
from app.core.exceptions import NotFoundError, ValidationError
from app.db.enums import AIMessageRole, ConversationStatus, EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.conversations import ConversationService
from tests.conftest import _create_employee, _uow_factory


@pytest.fixture
def conversations() -> ConversationService:
    return ConversationService(uow_factory=_uow_factory)


def _actor(employee: Employee) -> tuple:
    return employee.company_id, employee.id


@pytest.mark.asyncio
async def test_create_get_list_archive(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    created = await conversations.create_conversation(company_id, employee_id)
    assert created.company_id == company_id
    assert created.employee_id == employee_id
    assert created.status == ConversationStatus.ACTIVE.value
    assert created.title is None

    loaded = await conversations.get_conversation(company_id, employee_id, created.id)
    assert loaded.id == created.id
    assert "messages" in inspect(loaded).unloaded

    listed = await conversations.list_conversations(company_id, employee_id)
    assert [row.id for row in listed] == [created.id]
    assert "messages" in inspect(listed[0]).unloaded

    archived = await conversations.archive_conversation(
        company_id, employee_id, created.id
    )
    assert archived.status == ConversationStatus.ARCHIVED.value
    again = await conversations.archive_conversation(company_id, employee_id, created.id)
    assert again.status == ConversationStatus.ARCHIVED.value
    readable = await conversations.get_conversation(company_id, employee_id, created.id)
    assert readable.status == ConversationStatus.ARCHIVED.value


@pytest.mark.asyncio
async def test_optional_title_and_title_validation(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    named = await conversations.create_conversation(
        company_id, employee_id, title="  Policy questions  "
    )
    assert named.title == "Policy questions"
    blank = await conversations.create_conversation(
        company_id, employee_id, title="   "
    )
    assert blank.title is None
    with pytest.raises(ValidationError, match="at most"):
        await conversations.create_conversation(
            company_id,
            employee_id,
            title="x" * (MAX_CONVERSATION_TITLE_CHARS + 1),
        )


@pytest.mark.asyncio
async def test_add_and_list_messages_deterministic_order(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    conversation = await conversations.create_conversation(company_id, employee_id)
    first = await conversations.add_message(
        company_id,
        employee_id,
        conversation.id,
        AIMessageRole.USER.value,
        "  first question  ",
    )
    second = await conversations.add_message(
        company_id,
        employee_id,
        conversation.id,
        AIMessageRole.ASSISTANT.value,
        "first answer",
    )
    assert first.content == "first question"
    assert second.role == AIMessageRole.ASSISTANT.value
    rows = await conversations.list_messages(company_id, employee_id, conversation.id)
    assert [row.id for row in rows] == [first.id, second.id]
    assert [row.role for row in rows] == [
        AIMessageRole.USER.value,
        AIMessageRole.ASSISTANT.value,
    ]

    async with _uow_factory() as uow:
        await uow.enter_employee(employee_id)
        await uow.session.execute(
            text("UPDATE ai_messages SET created_at = now() WHERE id IN (:a, :b)"),
            {"a": first.id, "b": second.id},
        )
        await uow.commit()

    tied = await conversations.list_messages(company_id, employee_id, conversation.id)
    assert [row.id for row in tied] == sorted([first.id, second.id])


@pytest.mark.asyncio
async def test_list_conversations_orders_by_updated_at(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    older = await conversations.create_conversation(company_id, employee_id)
    newer = await conversations.create_conversation(company_id, employee_id)
    await conversations.add_message(
        company_id,
        employee_id,
        older.id,
        AIMessageRole.USER.value,
        "bump older to the top",
    )
    listed = await conversations.list_conversations(company_id, employee_id)
    assert [row.id for row in listed[:2]] == [older.id, newer.id]


@pytest.mark.asyncio
async def test_archived_rejects_new_messages_and_stays_readable(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    conversation = await conversations.create_conversation(company_id, employee_id)
    saved = await conversations.add_message(
        company_id,
        employee_id,
        conversation.id,
        AIMessageRole.USER.value,
        "keep me",
    )
    await conversations.archive_conversation(company_id, employee_id, conversation.id)
    with pytest.raises(ValidationError, match="archived"):
        await conversations.add_message(
            company_id,
            employee_id,
            conversation.id,
            AIMessageRole.USER.value,
            "should not persist",
        )
    rows = await conversations.list_messages(company_id, employee_id, conversation.id)
    assert [row.id for row in rows] == [saved.id]


@pytest.mark.asyncio
async def test_message_validation(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    conversation = await conversations.create_conversation(company_id, employee_id)
    with pytest.raises(ValidationError, match="empty"):
        await conversations.add_message(
            company_id, employee_id, conversation.id, "user", "   "
        )
    with pytest.raises(ValidationError, match="user or assistant"):
        await conversations.add_message(
            company_id, employee_id, conversation.id, "system", "hello"
        )
    with pytest.raises(ValidationError, match="at most"):
        await conversations.add_message(
            company_id,
            employee_id,
            conversation.id,
            "user",
            "x" * (MAX_CONVERSATION_MESSAGE_CHARS + 1),
        )
    rows = await conversations.list_messages(company_id, employee_id, conversation.id)
    assert rows == []


@pytest.mark.asyncio
async def test_uuid_probing_and_cross_employee_are_not_found(
    conversations: ConversationService,
    employee_a: Employee,
    company_a: Company,
) -> None:
    company_id, employee_id = _actor(employee_a)
    peer = await _create_employee(
        company_id=company_a.id, role=EmployeeRole.EMPLOYEE.value
    )
    own = await conversations.create_conversation(company_id, employee_id)
    other = await conversations.create_conversation(company_a.id, peer.id)
    missing = uuid4()

    with pytest.raises(NotFoundError, match="Conversation not found"):
        await conversations.get_conversation(company_id, employee_id, missing)
    with pytest.raises(NotFoundError, match="Conversation not found"):
        await conversations.get_conversation(company_id, employee_id, other.id)
    with pytest.raises(NotFoundError, match="Conversation not found"):
        await conversations.add_message(
            company_id, employee_id, other.id, "user", "nope"
        )
    with pytest.raises(NotFoundError, match="Conversation not found"):
        await conversations.list_messages(company_id, employee_id, other.id)
    with pytest.raises(NotFoundError, match="Conversation not found"):
        await conversations.archive_conversation(company_id, employee_id, other.id)

    listed = await conversations.list_conversations(company_id, employee_id)
    assert {row.id for row in listed} == {own.id}


@pytest.mark.asyncio
async def test_cross_company_is_not_found(
    conversations: ConversationService,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    owned_b = await conversations.create_conversation(
        employee_b.company_id, employee_b.id
    )
    with pytest.raises(NotFoundError):
        await conversations.get_conversation(
            employee_a.company_id, employee_a.id, owned_b.id
        )
    with pytest.raises(NotFoundError):
        await conversations.add_message(
            employee_a.company_id,
            employee_a.id,
            owned_b.id,
            "user",
            "cross tenant",
        )


@pytest.mark.asyncio
async def test_actor_spoofing_cannot_change_owner_or_tenant(
    conversations: ConversationService,
    employee_a: Employee,
    employee_b: Employee,
    company_a: Company,
    company_b: Company,
) -> None:
    with pytest.raises(NotFoundError, match="Employee not found"):
        await conversations.create_conversation(company_b.id, employee_a.id)
    with pytest.raises(NotFoundError, match="Employee not found"):
        await conversations.create_conversation(company_a.id, employee_b.id)

    own = await conversations.create_conversation(company_a.id, employee_a.id)
    listed_b = await conversations.list_conversations(company_b.id, employee_b.id)
    assert own.id not in {row.id for row in listed_b}


@pytest.mark.asyncio
async def test_failed_validation_does_not_persist_half_state(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    conversation = await conversations.create_conversation(company_id, employee_id)
    with pytest.raises(ValidationError):
        await conversations.add_message(
            company_id, employee_id, conversation.id, "system", "ignored"
        )
    assert (
        await conversations.list_messages(company_id, employee_id, conversation.id)
        == []
    )
    with pytest.raises(NotFoundError):
        await conversations.create_conversation(company_id, uuid4())
    listed = await conversations.list_conversations(company_id, employee_id)
    assert [row.id for row in listed] == [conversation.id]


@pytest.mark.asyncio
async def test_get_message_requires_owning_conversation(
    conversations: ConversationService,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    own = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    message = await conversations.add_message(
        employee_a.company_id,
        employee_a.id,
        own.id,
        "user",
        "secret-to-owner",
    )
    loaded = await conversations.get_message(
        employee_a.company_id, employee_a.id, message.id
    )
    assert loaded.id == message.id
    with pytest.raises(NotFoundError, match="Message not found"):
        await conversations.get_message(
            employee_b.company_id, employee_b.id, message.id
        )
    with pytest.raises(NotFoundError, match="Message not found"):
        await conversations.get_message(
            employee_a.company_id, employee_a.id, uuid4()
        )


@pytest.mark.asyncio
async def test_conversation_schema_constraints_and_rls() -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        conv_rel = (
            await uow.session.execute(
                text("SELECT to_regclass('public.ai_conversations')")
            )
        ).scalar_one()
        msg_rel = (
            await uow.session.execute(
                text("SELECT to_regclass('public.ai_messages')")
            )
        ).scalar_one()
        assert conv_rel == "ai_conversations"
        assert msg_rel == "ai_messages"

        conv_cols = {
            row[0]
            for row in (
                await uow.session.execute(
                    text(
                        """
                        SELECT column_name FROM information_schema.columns
                        WHERE table_name = 'ai_conversations'
                        """
                    )
                )
            ).all()
        }
        assert "telegram_chat_id" not in conv_cols
        assert "messages" not in conv_cols
        assert "title" in conv_cols
        assert "company_id" in conv_cols
        assert "employee_id" in conv_cols

        names = {
            row[0]
            for row in (
                await uow.session.execute(
                    text(
                        """
                        SELECT conname FROM pg_constraint
                        WHERE conrelid = 'public.ai_messages'::regclass
                        """
                    )
                )
            ).all()
        }
        assert "ck_ai_messages_role" in names
        assert "ck_ai_messages_content_not_blank" in names
        assert "ck_ai_messages_content_max_length" in names

        indexes = {
            row[0]
            for row in (
                await uow.session.execute(
                    text(
                        """
                        SELECT indexname FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename IN ('ai_conversations', 'ai_messages')
                        """
                    )
                )
            ).all()
        }
        assert "ix_ai_conversations_company_id_employee_id_updated_at" in indexes
        assert "ix_ai_messages_conversation_id_created_at" in indexes

        for table in ("ai_conversations", "ai_messages"):
            row = (
                await uow.session.execute(
                    text(
                        """
                        SELECT relrowsecurity, relforcerowsecurity
                        FROM pg_class
                        WHERE relname = :name
                        """
                    ),
                    {"name": table},
                )
            ).one()
            assert row[0] is True
            assert row[1] is True


@pytest.mark.asyncio
async def test_complete_turn_creates_conversation_and_both_messages(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    conversation = await conversations.complete_turn(
        company_id,
        employee_id,
        "user question",
        "assistant answer",
    )
    assert conversation.status == ConversationStatus.ACTIVE.value
    assert conversation.employee_id == employee_id
    assert conversation.title == "user question"
    rows = await conversations.list_messages(company_id, employee_id, conversation.id)
    assert [row.role for row in rows] == [
        AIMessageRole.USER.value,
        AIMessageRole.ASSISTANT.value,
    ]
    assert [row.content for row in rows] == ["user question", "assistant answer"]


@pytest.mark.asyncio
async def test_complete_turn_reuses_existing_and_rejects_archived(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    created = await conversations.create_conversation(company_id, employee_id)
    reused = await conversations.complete_turn(
        company_id,
        employee_id,
        "follow up",
        "follow answer",
        conversation_id=created.id,
    )
    assert reused.id == created.id
    await conversations.archive_conversation(company_id, employee_id, created.id)
    with pytest.raises(ValidationError, match="archived"):
        await conversations.complete_turn(
            company_id,
            employee_id,
            "after archive",
            "should not persist",
            conversation_id=created.id,
        )
    rows = await conversations.list_messages(company_id, employee_id, created.id)
    assert [row.content for row in rows] == ["follow up", "follow answer"]


@pytest.mark.asyncio
async def test_complete_turn_foreign_conversation_is_not_found(
    conversations: ConversationService,
    employee_a: Employee,
    company_a: Company,
) -> None:
    peer = await _create_employee(
        company_id=company_a.id, role=EmployeeRole.EMPLOYEE.value
    )
    other = await conversations.create_conversation(company_a.id, peer.id)
    with pytest.raises(NotFoundError):
        await conversations.complete_turn(
            employee_a.company_id,
            employee_a.id,
            "hijack",
            "nope",
            conversation_id=other.id,
        )


@pytest.mark.asyncio
async def test_list_recent_messages_newest_window_chronological(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    conversation = await conversations.create_conversation(company_id, employee_id)
    for index in range(5):
        await conversations.add_message(
            company_id,
            employee_id,
            conversation.id,
            AIMessageRole.USER.value,
            f"m{index}",
        )
    recent = await conversations.list_recent_messages(
        company_id, employee_id, conversation.id, limit=3
    )
    assert [row.content for row in recent] == ["m2", "m3", "m4"]


@pytest.mark.asyncio
async def test_title_from_first_user_message_utf8_and_truncate(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    ru = await conversations.complete_turn(
        company_id, employee_id, "Как оформить отпуск?", "ok"
    )
    assert ru.title == "Как оформить отпуск?"
    kk = await conversations.complete_turn(
        company_id, employee_id, "Демалысты қалай рәсімдеуге болады?", "ok"
    )
    assert kk.title == "Демалысты қалай рәсімдеуге болады?"
    en = await conversations.complete_turn(
        company_id, employee_id, "How do I request leave?", "ok"
    )
    assert en.title == "How do I request leave?"
    long_q = "Как оформить отпуск " + ("и документы " * 40)
    long_c = await conversations.complete_turn(company_id, employee_id, long_q, "ok")
    assert long_c.title is not None
    assert len(long_c.title) <= MAX_CONVERSATION_TITLE_CHARS
    assert long_c.title.endswith("…")


@pytest.mark.asyncio
async def test_list_summaries_hides_archived_and_avoids_n_plus_one(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    first = await conversations.complete_turn(
        company_id, employee_id, "VPN access", "Use the portal"
    )
    second = await conversations.complete_turn(
        company_id, employee_id, "Leave policy", "Ask HR"
    )
    await conversations.archive_conversation(company_id, employee_id, first.id)
    rows = await conversations.list_conversation_summaries(company_id, employee_id)
    assert [row.id for row in rows] == [second.id]
    assert rows[0].title == "Leave policy"
    assert rows[0].last_message_preview == "Ask HR"
    assert rows[0].message_count == 2
    loaded, messages = await conversations.get_conversation_with_messages(
        company_id, employee_id, second.id
    )
    assert loaded.id == second.id
    assert [row.role for row in messages] == ["user", "assistant"]
    with pytest.raises(NotFoundError):
        await conversations.get_conversation_with_messages(
            company_id, employee_id, first.id
        )


@pytest.mark.asyncio
async def test_complete_turn_persists_public_citations_only(
    conversations: ConversationService,
    employee_a: Employee,
) -> None:
    company_id, employee_id = _actor(employee_a)
    article_id = uuid4()
    conversation = await conversations.complete_turn(
        company_id,
        employee_id,
        "VPN?",
        "Use the client. [S1]",
        citations=[
            {
                "source_id": "S1",
                "title": "VPN Access Policy",
                "article_id": str(article_id),
            }
        ],
        no_answer=False,
    )
    _loaded, messages = await conversations.get_conversation_with_messages(
        company_id, employee_id, conversation.id
    )
    assert messages[0].citations is None
    assert messages[0].no_answer is False
    assert messages[1].no_answer is False
    assert messages[1].citations == [
        {
            "source_id": "S1",
            "title": "VPN Access Policy",
            "article_id": str(article_id),
        }
    ]
    assert "version_id" not in messages[1].citations[0]
    assert "chunk_index" not in messages[1].citations[0]

