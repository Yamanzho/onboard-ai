"""AIChatService: retrieve → context → LLM. No HTTP, no Telegram, no persistence."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenError, ValidationError
from app.db.enums import EmployeeRole, KnowledgeBodyFormat, KnowledgeVisibility, PlatformRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.chat import NO_ANSWER_MESSAGE, AIChatService
from app.services.ai.chunking import chunk_article
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.ai.llm import FakeLLMProvider
from app.services.ai.retriever import KnowledgeRetriever
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory


def _identity_question(title: str, body: str) -> str:
    chunks = chunk_article(
        title=title,
        body=body,
        body_format=KnowledgeBodyFormat.MARKDOWN.value,
    )
    return chunks[0]


@pytest.fixture
def chat_stack() -> tuple[ArticleService, AIChatService]:
    embeddings = FakeEmbeddingProvider()
    indexer = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=embeddings,
    )
    service = ArticleService(uow_factory=_uow_factory, chunk_indexer=indexer)
    retriever = KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=service,
        embedding_provider=embeddings,
    )
    chat = AIChatService(
        retriever=retriever,
        llm_provider=FakeLLMProvider(),
        uow_factory=_uow_factory,
    )
    return service, chat


async def test_chat_no_answer_when_corpus_empty(
    chat_stack: tuple[ArticleService, AIChatService],
    company_a: Company,
    employee_a: Employee,
) -> None:
    _service, chat = chat_stack
    result = await chat.answer(
        "How do I request vacation?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert result.no_answer is True
    assert result.status == "empty_retrieval"
    assert result.citations == ()
    assert result.answer == NO_ANSWER_MESSAGE


async def test_chat_answers_from_authorized_hits_only(
    chat_stack: tuple[ArticleService, AIChatService],
    company_a: Company,
    employee_a: Employee,
) -> None:
    service, chat = chat_stack
    created = await service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Vacation leave",
        body="Submit leave three working days in advance.",
        visibility=KnowledgeVisibility.COMPANY.value,
    )
    await service.publish_article(created.id, company_id=company_a.id)
    result = await chat.answer(
        _identity_question("Vacation leave", "Submit leave three working days in advance."),
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert result.no_answer is False
    assert result.status == "answered"
    assert result.hit_count >= 1
    assert result.citations
    assert result.citations[0].article_id == created.id
    assert result.citations[0].version_id is not None
    assert "[S1]" in result.answer


async def test_chat_does_not_call_llm_when_forced_no_answer_provider(
    chat_stack: tuple[ArticleService, AIChatService],
    company_a: Company,
    employee_a: Employee,
) -> None:
    service, _chat = chat_stack
    created = await service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="VPN",
        body="Remote access uses WireGuard.",
        visibility=KnowledgeVisibility.COMPANY.value,
    )
    await service.publish_article(created.id, company_id=company_a.id)
    retriever = KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=service,
        embedding_provider=FakeEmbeddingProvider(),
    )
    chat = AIChatService(
        retriever=retriever,
        llm_provider=FakeLLMProvider(force_no_answer=True),
        uow_factory=_uow_factory,
    )
    result = await chat.answer(
        _identity_question("VPN", "Remote access uses WireGuard."),
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert result.no_answer is True
    assert result.status == "no_answer"
    assert result.citations == ()


async def test_chat_rejects_empty_question(
    chat_stack: tuple[ArticleService, AIChatService],
    employee_a: Employee,
) -> None:
    _service, chat = chat_stack
    with pytest.raises(ValidationError, match="question"):
        await chat.answer(
            "  ",
            actor_company_id=employee_a.company_id,
            actor_employee_id=employee_a.id,
            actor_role=employee_a.role,
        )


async def test_chat_super_admin_forbidden(
    chat_stack: tuple[ArticleService, AIChatService],
    company_a: Company,
) -> None:
    _service, chat = chat_stack
    with pytest.raises(ForbiddenError, match="impersonation"):
        await chat.answer(
            "What is the vacation policy?",
            actor_company_id=company_a.id,
            actor_employee_id=uuid4(),
            actor_role=PlatformRole.SUPER_ADMIN.value,
        )


def test_chat_service_uses_conversation_service_not_orm() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "app/services/ai/chat.py").read_text(
        encoding="utf-8"
    )
    assert "ConversationService" in source
    assert "complete_turn" in source
    assert "AIConversation" not in source
    assert "ai_conversations" not in source
    assert "session.execute" not in source


@pytest.mark.asyncio
async def test_empty_retrieval_does_not_call_llm(
    chat_stack: tuple[ArticleService, AIChatService],
    employee_a: Employee,
) -> None:
    _service, chat = chat_stack

    class _BoomLLM(FakeLLMProvider):
        async def generate(self, *, system_prompt: str, user_prompt: str):
            raise AssertionError("LLM must not be called on empty retrieval")

    chat._llm_provider = _BoomLLM()
    result = await chat.answer(
        "How do I request vacation?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert result.no_answer is True
    assert result.status == "empty_retrieval"


@pytest.mark.asyncio
async def test_provider_failure_is_service_unavailable(
    chat_stack: tuple[ArticleService, AIChatService],
    company_a: Company,
    employee_a: Employee,
) -> None:
    from app.core.exceptions import ServiceUnavailableError

    service, chat = chat_stack
    created = await service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Vacation leave",
        body="Submit leave three working days in advance.",
        visibility=KnowledgeVisibility.COMPANY.value,
    )
    await service.publish_article(created.id, company_id=company_a.id)

    class _FailLLM(FakeLLMProvider):
        async def generate(self, *, system_prompt: str, user_prompt: str):
            raise ServiceUnavailableError("LLM provider unavailable")

    chat._llm_provider = _FailLLM()
    with pytest.raises(ServiceUnavailableError, match="unavailable"):
        await chat.answer(
            _identity_question(
                "Vacation leave", "Submit leave three working days in advance."
            ),
            actor_company_id=employee_a.company_id,
            actor_employee_id=employee_a.id,
            actor_role=employee_a.role,
        )


@pytest.mark.asyncio
async def test_chat_timeout_is_service_unavailable(
    employee_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from app.core.config import get_settings
    from app.core.exceptions import ServiceUnavailableError

    settings = get_settings()
    monkeypatch.setattr(settings, "ai_chat_timeout_seconds", 0.05)

    class _SlowRetriever:
        async def retrieve(self, *args: object, **kwargs: object):
            await asyncio.sleep(1)
            return []

    chat = AIChatService(
        retriever=_SlowRetriever(),  # type: ignore[arg-type]
        llm_provider=FakeLLMProvider(),
        uow_factory=_uow_factory,
    )
    with pytest.raises(ServiceUnavailableError, match="timed out"):
        await chat.answer(
            "How do I request vacation?",
            actor_company_id=employee_a.company_id,
            actor_employee_id=employee_a.id,
            actor_role=employee_a.role,
        )
