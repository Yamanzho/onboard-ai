"""AI-11B HTTP conversation lifecycle on POST /api/v1/ai/chat."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.exceptions import ServiceUnavailableError
from app.db.enums import ConversationStatus, EmployeeRole, KnowledgeBodyFormat
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.chat import NO_ANSWER_MESSAGE, AIChatService, ChatAnswer
from app.services.ai.chunking import chunk_article
from app.services.ai.conversations import ConversationService
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _create_employee, _uow_factory, auth_header
from tests.security.test_ai_retrieval_acl import _publish

CHAT_PATH = "/api/v1/ai/chat"


@pytest.fixture
def conversations() -> ConversationService:
    return ConversationService(uow_factory=_uow_factory)


@pytest.fixture
def indexed_articles() -> ArticleService:
    embeddings = FakeEmbeddingProvider()
    indexer = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=embeddings,
    )
    return ArticleService(uow_factory=_uow_factory, chunk_indexer=indexer)


def _identity(title: str, body: str) -> str:
    chunks = chunk_article(
        title=title,
        body=body,
        body_format=KnowledgeBodyFormat.MARKDOWN.value,
    )
    return chunks[0]


@pytest.mark.asyncio
async def test_message_only_creates_conversation(
    api_client: AsyncClient,
    employee_a: Employee,
    conversations: ConversationService,
) -> None:
    response = await api_client.post(
        CHAT_PATH,
        json={"message": "How do I get VPN?"},
        headers=auth_header(employee_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    conversation_id = UUID(body["conversation_id"])
    loaded = await conversations.get_conversation(
        employee_a.company_id, employee_a.id, conversation_id
    )
    assert loaded.status == ConversationStatus.ACTIVE.value
    assert loaded.employee_id == employee_a.id
    assert loaded.company_id == employee_a.company_id
    assert body["no_answer"] is True
    assert body["answer"] == NO_ANSWER_MESSAGE


@pytest.mark.asyncio
async def test_message_plus_conversation_id_reuses_thread(
    api_client: AsyncClient,
    employee_a: Employee,
    conversations: ConversationService,
) -> None:
    first = await api_client.post(
        CHAT_PATH,
        json={"message": "How do I get VPN?"},
        headers=auth_header(employee_a),
    )
    conversation_id = first.json()["conversation_id"]
    second = await api_client.post(
        CHAT_PATH,
        json={
            "message": "Who should I write to?",
            "conversation_id": conversation_id,
        },
        headers=auth_header(employee_a),
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == conversation_id
    messages = await conversations.list_messages(
        employee_a.company_id, employee_a.id, UUID(conversation_id)
    )
    assert len(messages) == 4
    assert messages[0].content == "How do I get VPN?"
    assert messages[2].content == "Who should I write to?"


@pytest.mark.asyncio
async def test_unknown_conversation_is_404(
    api_client: AsyncClient,
    employee_a: Employee,
) -> None:
    response = await api_client.post(
        CHAT_PATH,
        json={"message": "hello", "conversation_id": str(uuid4())},
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found"}


@pytest.mark.asyncio
async def test_archived_conversation_is_400_and_does_not_unarchive(
    api_client: AsyncClient,
    employee_a: Employee,
    conversations: ConversationService,
) -> None:
    created = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    await conversations.archive_conversation(
        employee_a.company_id, employee_a.id, created.id
    )
    response = await api_client.post(
        CHAT_PATH,
        json={"message": "hello", "conversation_id": str(created.id)},
        headers=auth_header(employee_a),
    )
    assert response.status_code == 400
    loaded = await conversations.get_conversation(
        employee_a.company_id, employee_a.id, created.id
    )
    assert loaded.status == ConversationStatus.ARCHIVED.value
    assert (
        await conversations.list_messages(
            employee_a.company_id, employee_a.id, created.id
        )
        == []
    )


@pytest.mark.asyncio
async def test_peer_employee_cannot_continue_conversation(
    api_client: AsyncClient,
    company_a: Company,
    employee_a: Employee,
    conversations: ConversationService,
) -> None:
    owned = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    peer = await _create_employee(
        company_id=company_a.id, role=EmployeeRole.EMPLOYEE.value
    )
    response = await api_client.post(
        CHAT_PATH,
        json={"message": "hello", "conversation_id": str(owned.id)},
        headers=auth_header(peer),
    )
    assert response.status_code == 404
    assert "another" not in response.text.lower()
    assert "belong" not in response.text.lower()


@pytest.mark.asyncio
async def test_company_b_cannot_continue_company_a_conversation(
    api_client: AsyncClient,
    employee_a: Employee,
    employee_b: Employee,
    conversations: ConversationService,
) -> None:
    owned = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    response = await api_client.post(
        CHAT_PATH,
        json={"message": "hello", "conversation_id": str(owned.id)},
        headers=auth_header(employee_b),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_hr_and_admin_cannot_continue_employee_conversation(
    api_client: AsyncClient,
    employee_a: Employee,
    hr_a: Employee,
    admin_a: Employee,
    conversations: ConversationService,
) -> None:
    owned = await conversations.create_conversation(
        employee_a.company_id, employee_a.id
    )
    for actor in (hr_a, admin_a):
        response = await api_client.post(
            CHAT_PATH,
            json={"message": "hello", "conversation_id": str(owned.id)},
            headers=auth_header(actor),
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_llm_failure_is_503_without_new_conversation(
    api_client: AsyncClient,
    employee_a: Employee,
    company_a: Company,
    indexed_articles: ArticleService,
    conversations: ConversationService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _publish(
        indexed_articles,
        company_a,
        title="Vacation leave",
        body="Submit leave three working days in advance.",
    )
    original = AIChatService.answer

    async def boom(self: AIChatService, question: str, **kwargs: object) -> ChatAnswer:
        if kwargs.get("conversation_id") is None:
            raise ServiceUnavailableError("LLM provider unavailable")
        return await original(self, question, **kwargs)

    monkeypatch.setattr(AIChatService, "answer", boom)
    before = await conversations.list_conversations(
        employee_a.company_id, employee_a.id
    )
    response = await api_client.post(
        CHAT_PATH,
        json={
            "message": _identity(
                "Vacation leave", "Submit leave three working days in advance."
            )
        },
        headers=auth_header(employee_a),
    )
    assert response.status_code == 503
    after = await conversations.list_conversations(
        employee_a.company_id, employee_a.id
    )
    assert [row.id for row in after] == [row.id for row in before]


@pytest.mark.asyncio
async def test_answered_turn_persists_user_and_assistant(
    api_client: AsyncClient,
    employee_a: Employee,
    company_a: Company,
    indexed_articles: ArticleService,
    conversations: ConversationService,
) -> None:
    await _publish(
        indexed_articles,
        company_a,
        title="Vacation leave",
        body="Submit leave three working days in advance.",
    )
    response = await api_client.post(
        CHAT_PATH,
        json={
            "message": _identity(
                "Vacation leave", "Submit leave three working days in advance."
            )
        },
        headers=auth_header(employee_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["no_answer"] is False
    assert body["citations"]
    messages = await conversations.list_messages(
        employee_a.company_id, employee_a.id, UUID(body["conversation_id"])
    )
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    assert messages[1].content != "LLM provider unavailable"
