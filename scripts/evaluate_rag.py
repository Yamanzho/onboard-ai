#!/usr/bin/env python3
"""AI-8 end-to-end RAG evaluation against a disposable synthetic tenant.

Default providers are FakeEmbeddingProvider + FakeLLMProvider (no network).
Live OpenAI embeddings and LLM are opt-in:

    ONBOARDAI_AI7_LIVE_OPENAI=1 python -m scripts.evaluate_rag --live-openai

Does not change ArticleService ACL, retrieval, prompts, top_k, or min_score.
Does not log API keys or write secrets into reports.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.core.exceptions import ValidationError  # noqa: E402
from app.db.enums import EmployeeRole  # noqa: E402
from app.services.ai.chat import AIChatService  # noqa: E402
from app.services.ai.conversations import ConversationService  # noqa: E402
from app.services.ai.embeddings import FakeEmbeddingProvider  # noqa: E402
from app.services.ai.evaluation import LIVE_OPENAI_ENV, live_openai_enabled  # noqa: E402
from app.services.ai.indexer import KnowledgeChunkIndexer  # noqa: E402
from app.services.ai.llm import FakeLLMProvider  # noqa: E402
from app.services.ai.openai_embeddings import OpenAIEmbeddingProvider  # noqa: E402
from app.services.ai.openai_llm import OpenAILLMProvider  # noqa: E402
from app.services.ai.rag_eval import (  # noqa: E402
    DEFAULT_REPORT_JSON,
    DEFAULT_REPORT_MD,
    render_rag_markdown,
    write_rag_reports,
)
from app.services.ai.rag_eval_runner import run_rag_evaluation  # noqa: E402
from app.services.ai.retriever import KnowledgeRetriever  # noqa: E402
from app.services.knowledge.article_service import ArticleService  # noqa: E402
from tests.conftest import (  # noqa: E402
    _create_company,
    _create_employee,
    _delete_company,
    _uow_factory,
)

logger = logging.getLogger("evaluate_rag")


def _providers(*, live_openai: bool):
    if not live_openai:
        return FakeEmbeddingProvider(), FakeLLMProvider(), "fake"
    if not live_openai_enabled():
        raise ValidationError(
            f"live OpenAI evaluation requires {LIVE_OPENAI_ENV}=1"
        )
    settings = get_settings()
    embedding_key = settings.ai_embedding_api_key.get_secret_value().strip()
    llm_key = settings.ai_llm_api_key.get_secret_value().strip()
    if not embedding_key or not llm_key:
        raise ValidationError(
            "AI_EMBEDDING_API_KEY/AI_LLM_API_KEY or OPENAI_API_KEY is required "
            "for --live-openai"
        )
    embeddings = OpenAIEmbeddingProvider(api_key=embedding_key)
    llm = OpenAILLMProvider(api_key=llm_key, model=settings.ai_llm_model)
    return embeddings, llm, embeddings.model


async def _evaluate_once(*, live_openai: bool):
    embeddings, llm, embedding_name = _providers(live_openai=live_openai)
    company_a = await _create_company(name="AI-8 RAG Eval A")
    company_b = await _create_company(name="AI-8 RAG Eval B")
    try:
        employee_a = await _create_employee(
            company_id=company_a.id, role=EmployeeRole.EMPLOYEE.value
        )
        peer = await _create_employee(
            company_id=company_a.id, role=EmployeeRole.EMPLOYEE.value
        )
        employee_b = await _create_employee(
            company_id=company_b.id, role=EmployeeRole.EMPLOYEE.value
        )
        indexer = KnowledgeChunkIndexer(
            uow_factory=_uow_factory,
            embedding_provider=embeddings,
        )
        article_service = ArticleService(
            uow_factory=_uow_factory,
            chunk_indexer=indexer,
        )
        retriever = KnowledgeRetriever(
            uow_factory=_uow_factory,
            article_service=article_service,
            embedding_provider=embeddings,
        )
        conversations = ConversationService(uow_factory=_uow_factory)
        chat = AIChatService(
            retriever=retriever,
            llm_provider=llm,
            conversation_service=conversations,
            uow_factory=_uow_factory,
        )
        report, _seeded = await run_rag_evaluation(
            article_service=article_service,
            retriever=retriever,
            chat=chat,
            llm=llm,
            company_a=company_a,
            company_b=company_b,
            employee_a=employee_a,
            peer=peer,
            employee_b=employee_b,
            embedding_provider=embedding_name,
            live_openai=live_openai,
        )
        logger.info(
            "rag_eval_complete live_openai=%s embedding=%s llm=%s cases=%s",
            live_openai,
            embedding_name,
            llm.model,
            report.dataset_size,
        )
        return report
    finally:
        await _delete_company(company_a.id)
        await _delete_company(company_b.id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-openai",
        action="store_true",
        help=f"Use OpenAI embeddings+LLM (requires {LIVE_OPENAI_ENV}=1 and keys)",
    )
    parser.add_argument(
        "--write-report",
        action="store_true",
        help=f"Write {DEFAULT_REPORT_MD} and {DEFAULT_REPORT_JSON}",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    report = asyncio.run(_evaluate_once(live_openai=args.live_openai))
    markdown = render_rag_markdown(report)
    print(markdown)
    if args.write_report:
        write_rag_reports(report)
        logger.info("wrote_report md=%s json=%s", DEFAULT_REPORT_MD, DEFAULT_REPORT_JSON)


if __name__ == "__main__":
    main()
