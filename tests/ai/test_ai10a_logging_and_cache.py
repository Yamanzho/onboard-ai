"""AI-10A: logs stay free of secrets; eval cache is not a production path."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.core.request_id import bind_request_id, reset_request_id
from app.db.models.employee import Employee
from app.services.ai.chat import AIChatService
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.ai.llm import FakeLLMProvider
from app.services.ai.retriever import KnowledgeRetriever
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory

ROOT = Path(__file__).resolve().parents[2]


def test_production_chat_does_not_read_eval_cache() -> None:
    paths = [
        ROOT / "app" / "services" / "ai" / "chat.py",
        ROOT / "app" / "api" / "v1" / "ai.py",
        ROOT / "app" / "bot" / "handlers" / "ai.py",
        ROOT / "app" / "bot" / "services" / "ai_client.py",
        ROOT / "app" / "services" / "ai" / "retriever.py",
        ROOT / "app" / "services" / "ai" / "openai_embeddings.py",
        ROOT / "app" / "services" / "ai" / "openai_llm.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert ".ai7_embedding_cache" not in combined
    assert "eval_cache_path" not in combined
    assert "load_embedding_cache" not in combined


@pytest.mark.asyncio
async def test_chat_logs_omit_question_and_answer(
    employee_a: Employee,
    caplog: pytest.LogCaptureFixture,
) -> None:
    embeddings = FakeEmbeddingProvider()
    indexer = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=embeddings,
    )
    articles = ArticleService(uow_factory=_uow_factory, chunk_indexer=indexer)
    chat = AIChatService(
        retriever=KnowledgeRetriever(
            uow_factory=_uow_factory,
            article_service=articles,
            embedding_provider=embeddings,
        ),
        llm_provider=FakeLLMProvider(),
        uow_factory=_uow_factory,
    )
    question = f"UNIQUE_CHAT_QUESTION_{uuid4().hex}"
    token = bind_request_id("req-unit-test-correlation")
    try:
        with caplog.at_level("INFO"):
            result = await chat.answer(
                question,
                actor_company_id=employee_a.company_id,
                actor_employee_id=employee_a.id,
                actor_role=employee_a.role,
            )
    finally:
        reset_request_id(token)
    combined = " ".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("app.")
    )
    assert question not in combined
    assert result.answer not in combined or result.no_answer is True
    assert "req-unit-test-correlation" in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined
    assert "sk-" not in combined
