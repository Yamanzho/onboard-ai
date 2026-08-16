"""AI-8 end-to-end RAG evaluation through AIChatService + Fake providers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.ai_constants import DEFAULT_RETRIEVAL_TOP_K
from app.db.enums import EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.chat import AIChatService
from app.services.ai.conversations import ConversationService
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.ai.llm import FakeLLMProvider
from app.services.ai.rag_eval import render_rag_markdown, write_rag_reports
from app.services.ai.rag_eval_runner import run_rag_evaluation
from app.services.ai.retriever import KnowledgeRetriever
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _create_employee, _uow_factory

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def rag_eval_stack() -> tuple[
    ArticleService, KnowledgeRetriever, AIChatService, FakeLLMProvider
]:
    embeddings = FakeEmbeddingProvider()
    llm = FakeLLMProvider()
    indexer = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=embeddings,
    )
    articles = ArticleService(uow_factory=_uow_factory, chunk_indexer=indexer)
    retriever = KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=articles,
        embedding_provider=embeddings,
    )
    chat = AIChatService(
        retriever=retriever,
        llm_provider=llm,
        conversation_service=ConversationService(uow_factory=_uow_factory),
        uow_factory=_uow_factory,
    )
    return articles, retriever, chat, llm


async def test_fake_rag_eval_measures_pipeline_and_isolates_tenants(
    rag_eval_stack: tuple[
        ArticleService, KnowledgeRetriever, AIChatService, FakeLLMProvider
    ],
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    articles, retriever, chat, llm = rag_eval_stack
    peer = await _create_employee(
        company_id=company_a.id, role=EmployeeRole.EMPLOYEE.value
    )
    employee_b = await _create_employee(
        company_id=company_b.id, role=EmployeeRole.EMPLOYEE.value
    )
    report, _seeded = await run_rag_evaluation(
        article_service=articles,
        retriever=retriever,
        chat=chat,
        llm=llm,
        company_a=company_a,
        company_b=company_b,
        employee_a=employee_a,
        peer=peer,
        employee_b=employee_b,
        embedding_provider="fake",
        live_openai=False,
    )
    assert report.dataset_size >= 20
    assert report.live_openai is False
    assert report.top_k == DEFAULT_RETRIEVAL_TOP_K
    assert report.security_passed
    retrieved = {
        key for row in report.cases for key in row.retrieved_keys
    }
    cited = {key for row in report.cases for key in row.cited_keys}
    assert "bonus-b-en" not in retrieved
    assert "bonus-b-en" not in cited
    assert [row.case_id for row in report.cases if row.leaked_forbidden] == []
    assert report.latency.n == report.dataset_size
    markdown = render_rag_markdown(report)
    assert "# AI-8 Evaluation Report" in markdown
    assert "Small evaluation sample" in markdown
    assert "Live OpenAI embeddings+LLM: **NOT MEASURED**" in markdown
    assert "Fake embeddings + FakeLLM: **MEASURED**" in markdown
    if os.environ.get("ONBOARDAI_AI8_WRITE_REPORT") == "1":
        write_rag_reports(report)


def test_eval_does_not_change_production_retrieval_defaults() -> None:
    assert DEFAULT_RETRIEVAL_TOP_K == 5
    chat = (ROOT / "app" / "services" / "ai" / "chat.py").read_text(encoding="utf-8")
    assert "min_score=" not in chat
    prompts = (ROOT / "app" / "services" / "ai" / "prompts.py").read_text(
        encoding="utf-8"
    )
    assert "You are OnboardAI's knowledge-base assistant" in prompts
