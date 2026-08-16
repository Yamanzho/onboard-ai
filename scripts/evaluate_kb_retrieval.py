#!/usr/bin/env python3
"""AI-7/AI-8 retrieval evaluation against a disposable synthetic tenant.

Default provider is FakeEmbeddingProvider (no network). Live OpenAI is opt-in:

    ONBOARDAI_AI7_LIVE_OPENAI=1 python -m scripts.evaluate_kb_retrieval --live-openai

Embeddings are batched and cached under .ai7_embedding_cache/ (gitignored,
model-specific files). Does not change ArticleService ACL or enable a
production min_score. Does not log API keys or raw query text.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.exceptions import ValidationError  # noqa: E402
from app.db.enums import EmployeeRole  # noqa: E402
from app.services.ai.embeddings import FakeEmbeddingProvider  # noqa: E402
from app.services.ai.eval_runner import run_retrieval_evaluation  # noqa: E402
from app.services.ai.evaluation import (  # noqa: E402
    LIVE_OPENAI_ENV,
    CachedEmbeddingProvider,
    eval_cache_path,
    live_openai_enabled,
    render_ai8_markdown_report,
    render_markdown_report,
)
from app.services.ai.indexer import KnowledgeChunkIndexer  # noqa: E402
from app.services.ai.openai_embeddings import OpenAIEmbeddingProvider  # noqa: E402
from app.services.ai.retriever import KnowledgeRetriever  # noqa: E402
from app.services.knowledge.article_service import ArticleService  # noqa: E402
from tests.conftest import (  # noqa: E402
    _create_company,
    _create_employee,
    _delete_company,
    _uow_factory,
)

logger = logging.getLogger("evaluate_kb_retrieval")
DEFAULT_AI7_REPORT = _ROOT / "docs" / "ai" / "ai7-retrieval-evaluation.md"
DEFAULT_AI8_REPORT = _ROOT / "docs" / "ai" / "ai8-real-retrieval-evaluation.md"


def _provider(*, live_openai: bool):
    if not live_openai:
        inner = FakeEmbeddingProvider()
        cached = CachedEmbeddingProvider(
            inner,
            eval_cache_path(_ROOT, "fake"),
            model="fake",
            allow_network=True,
        )
        return cached, "fake"
    if not live_openai_enabled():
        raise ValidationError(
            f"live OpenAI evaluation requires {LIVE_OPENAI_ENV}=1"
        )
    settings = get_settings()
    key = settings.ai_embedding_api_key.get_secret_value().strip()
    if not key:
        raise ValidationError(
            "AI_EMBEDDING_API_KEY or OPENAI_API_KEY is required for --live-openai"
        )
    inner = OpenAIEmbeddingProvider(api_key=key)
    cached = CachedEmbeddingProvider(
        inner,
        eval_cache_path(_ROOT, inner.model),
        model=inner.model,
        allow_network=True,
    )
    return cached, inner.model


async def _evaluate_once(*, live_openai: bool):
    provider, name = _provider(live_openai=live_openai)
    company_a = await _create_company(name="AI-8 Eval A")
    company_b = await _create_company(name="AI-8 Eval B")
    try:
        employee_a = await _create_employee(
            company_id=company_a.id,
            role=EmployeeRole.EMPLOYEE.value,
        )
        indexer = KnowledgeChunkIndexer(
            uow_factory=_uow_factory,
            embedding_provider=provider,
        )
        article_service = ArticleService(
            uow_factory=_uow_factory,
            chunk_indexer=indexer,
        )
        retriever = KnowledgeRetriever(
            uow_factory=_uow_factory,
            article_service=article_service,
            embedding_provider=provider,
        )
        report, _seeded = await run_retrieval_evaluation(
            article_service=article_service,
            retriever=retriever,
            company_a=company_a,
            company_b=company_b,
            employee_a=employee_a,
            provider_name=name,
            live_openai=live_openai,
            model=getattr(provider, "model", name),
            dimension=getattr(provider, "dimension", KB_CHUNK_VECTOR_DIMENSION),
        )
        report.cache_hits = getattr(provider, "cache_hits", 0)
        report.network_batches = getattr(provider, "network_batches", 0)
        report.embedded_texts = getattr(provider, "embedded_texts", 0)
        logger.info(
            "eval_complete provider=%s live_openai=%s cache_hits=%s "
            "network_batches=%s embedded_texts=%s cases=%s",
            name,
            live_openai,
            report.cache_hits,
            report.network_batches,
            report.embedded_texts,
            report.total_cases,
        )
        return report
    finally:
        await _delete_company(company_a.id)
        await _delete_company(company_b.id)


async def _run(*, live_openai: bool, write_report: Path | None) -> int:
    fake_report = await _evaluate_once(live_openai=False)
    openai_report = None
    if live_openai:
        openai_report = await _evaluate_once(live_openai=True)
    if live_openai:
        markdown = render_ai8_markdown_report(
            fake=fake_report,
            openai=openai_report,
            measured_at=datetime.now(UTC).date().isoformat(),
        )
    else:
        markdown = render_markdown_report(fake_report)
    print(markdown)
    if write_report is not None:
        write_report.parent.mkdir(parents=True, exist_ok=True)
        write_report.write_text(markdown, encoding="utf-8")
        logger.info("wrote_report path=%s", write_report)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live-openai",
        action="store_true",
        help=f"Use OpenAI embeddings (requires {LIVE_OPENAI_ENV}=1 and an API key)",
    )
    parser.add_argument(
        "--write-report",
        nargs="?",
        const="AUTO",
        default=None,
        help="Write markdown report (default AI-8 path if --live-openai, else AI-7)",
    )
    parser.add_argument(
        "--write-ai8-report",
        action="store_true",
        help=f"Write the combined AI-8 report to {DEFAULT_AI8_REPORT}",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    if args.write_report == "AUTO":
        report_path = DEFAULT_AI8_REPORT if args.live_openai else DEFAULT_AI7_REPORT
    elif args.write_report:
        report_path = Path(args.write_report)
    elif args.write_ai8_report:
        report_path = DEFAULT_AI8_REPORT
    else:
        report_path = None
    if args.write_ai8_report and not args.live_openai:
        # Combined AI-8 document with Fake MEASURED and OpenAI NOT MEASURED.
        async def _ai8_placeholder() -> int:
            fake_report = await _evaluate_once(live_openai=False)
            markdown = render_ai8_markdown_report(
                fake=fake_report,
                openai=None,
                measured_at=datetime.now(UTC).date().isoformat(),
            )
            print(markdown)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(markdown, encoding="utf-8")
            logger.info("wrote_report path=%s", report_path)
            return 0

        raise SystemExit(asyncio.run(_ai8_placeholder()))
    raise SystemExit(
        asyncio.run(_run(live_openai=args.live_openai, write_report=report_path))
    )


if __name__ == "__main__":
    main()
