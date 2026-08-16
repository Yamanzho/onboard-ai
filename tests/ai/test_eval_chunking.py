"""AI-7 chunking evaluation. Do not redesign the chunker unless a defect is proven."""

from __future__ import annotations

from app.core.ai_constants import MAX_CHUNKS_PER_ARTICLE
from app.db.models.company import Company
from app.db.uow import UnitOfWork
from app.services.ai.chunking import chunk_article, extract_index_text
from app.services.ai.eval_corpus import (
    CHUNKING_HTML_RU,
    CHUNKING_KK_BULLETS,
    EVAL_ARTICLES,
)
from app.services.ai.eval_runner import evaluate_chunking_offline, seed_eval_articles
from app.services.knowledge.article_service import ArticleService


def test_offline_chunking_evaluation_passes() -> None:
    result = evaluate_chunking_offline()
    assert result["passed"] is True, result["failures"]
    assert result["failures"] == []


def test_short_medium_long_markdown_and_unicode() -> None:
    by_kind = {article.chunking: article for article in EVAL_ARTICLES if article.chunking}
    short = chunk_article(
        title=by_kind["short"].title,
        body=by_kind["short"].body,
        body_format=by_kind["short"].body_format,
    )
    medium = chunk_article(
        title=by_kind["medium"].title,
        body=by_kind["medium"].body,
        body_format=by_kind["medium"].body_format,
    )
    long = chunk_article(
        title=by_kind["long"].title,
        body=by_kind["long"].body,
        body_format=by_kind["long"].body_format,
    )
    table = chunk_article(
        title=by_kind["table"].title,
        body=by_kind["table"].body,
        body_format=by_kind["table"].body_format,
    )
    html = chunk_article(
        title=CHUNKING_HTML_RU.title,
        body=CHUNKING_HTML_RU.body,
        body_format=CHUNKING_HTML_RU.body_format,
    )
    kk = chunk_article(
        title=CHUNKING_KK_BULLETS.title,
        body=CHUNKING_KK_BULLETS.body,
        body_format=CHUNKING_KK_BULLETS.body_format,
    )
    assert len(short) == 1
    assert 1 <= len(medium) <= MAX_CHUNKS_PER_ARTICLE
    assert 2 <= len(long) <= MAX_CHUNKS_PER_ARTICLE
    assert "Alatau" in "\n".join(table)
    assert "Medeu" in "\n".join(table)
    assert "<script>" not in html[0].lower()
    assert "политику" in html[0]
    assert "ғұқөң" in html[0]
    assert "Бэдж" in kk[0]
    assert "ә" in kk[0]


async def test_chunk_rows_keep_article_and_version(
    article_service: ArticleService,
    company_a: Company,
    company_b: Company,
) -> None:
    sample = next(article for article in EVAL_ARTICLES if article.key == "conduct-ru")
    seeded = await seed_eval_articles(
        article_service,
        company_a=company_a,
        company_b=company_b,
        articles=(sample,),
    )
    article_id = seeded.keys_to_ids["conduct-ru"]
    version_id = seeded.version_ids["conduct-ru"]
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        rows = await uow.knowledge_article_chunks.list_by_article_id(article_id)
    assert rows
    assert all(row.article_id == article_id for row in rows)
    assert all(row.version_id == version_id for row in rows)
    assert all(row.company_id == company_a.id for row in rows)
    expected = chunk_article(title=sample.title, body=sample.body, body_format=sample.body_format)
    assert [row.chunk_index for row in rows] == list(range(len(rows)))
    title_n, _body = extract_index_text(
        title=sample.title, body=sample.body, body_format=sample.body_format
    )
    assert all(row.content.startswith(title_n) for row in rows)
    assert len(rows) == len(expected)
