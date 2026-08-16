"""AI-7 retrieval evaluation through KnowledgeRetriever + FakeEmbeddingProvider."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.ai_constants import DEFAULT_RETRIEVAL_TOP_K
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.eval_corpus import EVAL_CASES, answerable_cases, no_answer_cases
from app.services.ai.eval_runner import run_retrieval_evaluation
from app.services.ai.evaluation import EVAL_TOP_KS, render_markdown_report
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.ai.retriever import KnowledgeRetriever
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def eval_stack() -> tuple[ArticleService, KnowledgeRetriever]:
    provider = FakeEmbeddingProvider()
    indexer = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=provider,
    )
    service = ArticleService(uow_factory=_uow_factory, chunk_indexer=indexer)
    retriever = KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=service,
        embedding_provider=provider,
    )
    return service, retriever


async def test_fake_provider_eval_runs_and_isolates_tenants(
    eval_stack: tuple[ArticleService, KnowledgeRetriever],
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    service, retriever = eval_stack
    report, seeded = await run_retrieval_evaluation(
        article_service=service,
        retriever=retriever,
        company_a=company_a,
        company_b=company_b,
        employee_a=employee_a,
        provider_name="fake",
        live_openai=False,
    )
    assert report.total_cases == len(EVAL_CASES)
    assert report.answerable_cases == len(answerable_cases())
    assert report.no_answer_cases == len(no_answer_cases())
    assert report.foreign_leaks == 0
    assert report.live_openai is False
    assert report.provider_name == "fake"
    leaked = {
        article_id
        for outcome in report.outcomes
        for article_id in outcome.hit_article_ids
    }
    assert seeded.keys_to_ids["bonus-b-en"] not in leaked
    for k in EVAL_TOP_KS:
        assert 0.0 <= report.recall[k].recall <= 1.0
        assert report.recall[k].total == report.answerable_cases
    exact = [item for item in report.outcomes if item.exact_phrase]
    assert exact
    assert all(item.article_hit_at[1] for item in exact)
    assert report.no_answer_with_hits == report.no_answer_cases
    assert report.same_language_recall[5].total > 0
    assert report.recall_by_pair
    assert "kk→en" in report.recall_by_pair
    markdown = render_markdown_report(report)
    assert "Recall@1" in markdown
    assert "NO_ANSWER_CASES" in markdown
    if os.environ.get("ONBOARDAI_AI7_WRITE_REPORT") == "1":
        target = ROOT / "docs" / "ai" / "ai7-retrieval-evaluation.md"
        target.write_text(markdown, encoding="utf-8")


def test_eval_does_not_change_production_top_k() -> None:
    assert DEFAULT_RETRIEVAL_TOP_K == 5


def test_eval_does_not_register_public_search_route() -> None:
    from app.main import app

    paths = " ".join(app.openapi()["paths"])
    assert "/ai/search" not in paths
    assert "/rag/query" not in paths
    assert "/api/v1/ai/chat" in paths
    readme = (ROOT / "app" / "api" / "v1" / "router.py").read_text(encoding="utf-8")
    assert "ai/search" not in readme
    assert "ai_router" in readme
