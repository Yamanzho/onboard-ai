"""Pure AI-7 metric helpers. No database, no OpenAI network."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.evaluation import (
    LIVE_OPENAI_ENV,
    THRESHOLD_CANDIDATES,
    CachedEmbeddingProvider,
    CaseOutcome,
    article_in_top_k,
    build_report,
    live_openai_enabled,
    recall_at_k,
    render_ai8_markdown_report,
    render_markdown_report,
    score_stats,
    threshold_analysis,
)
from app.services.ai.retriever import RetrievalHit


def _hit(article_id, score: float = 0.9) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=uuid4(),
        article_id=article_id,
        version_id=uuid4(),
        chunk_index=0,
        article_title="T",
        content="c",
        score=score,
    )


def test_article_in_top_k_and_recall() -> None:
    target = uuid4()
    other = uuid4()
    hits = [_hit(other, 0.9), _hit(target, 0.8), _hit(uuid4(), 0.1)]
    assert not article_in_top_k(hits, (target,), 1)
    assert article_in_top_k(hits, (target,), 2)
    measured = recall_at_k([True, False, True])
    assert measured.total == 3
    assert measured.hits == 2
    assert measured.misses == 1
    assert measured.recall == pytest.approx(2 / 3)


def test_score_stats_empty_and_median() -> None:
    empty = score_stats([])
    assert empty.count == 0
    assert empty.mean is None
    stats = score_stats([0.2, 0.4, 0.9])
    assert stats.min == 0.2
    assert stats.max == 0.9
    assert stats.median == 0.4


def _outcome(
    *,
    no_answer: bool,
    top: float | None,
    hit5: bool,
) -> CaseOutcome:
    return CaseOutcome(
        case_id="x",
        question="q",
        language="en",
        cross_language=False,
        expect_no_answer=no_answer,
        expected_keys=("a",) if not no_answer else (),
        expected_article_ids=(),
        hit_keys=(),
        hit_article_ids=(),
        scores=(top,) if top is not None else (),
        top_score=top,
        exact_phrase=False,
        article_hit_at={1: hit5, 3: hit5, 5: hit5, 10: hit5},
        expected_chunk_index=None,
        chunk_index_hit=None,
        leaked_foreign_article=False,
    )


def test_threshold_analysis_separates_no_answer() -> None:
    outcomes = [
        _outcome(no_answer=False, top=0.8, hit5=True),
        _outcome(no_answer=False, top=0.2, hit5=True),
        _outcome(no_answer=True, top=0.7, hit5=False),
        _outcome(no_answer=True, top=0.1, hit5=False),
    ]
    rows = {row.threshold: row for row in threshold_analysis(outcomes, k=5)}
    mid = rows[0.50]
    assert mid.true_positives == 1
    assert mid.false_negatives == 1
    assert mid.false_positives == 1
    assert mid.true_negatives == 1
    assert mid.precision == pytest.approx(0.5)
    assert mid.recall == pytest.approx(0.5)
    assert mid.f1 == pytest.approx(0.5)
    assert 0.20 in rows
    assert 0.90 in rows


def test_report_markdown_contains_required_headings() -> None:
    report = build_report(
        provider_name="fake",
        live_openai=False,
        outcomes=[
            _outcome(no_answer=False, top=0.9, hit5=True),
            _outcome(no_answer=True, top=0.2, hit5=False),
        ],
        chunking={"passed": True},
    )
    text = render_markdown_report(report)
    for heading in (
        "# AI-7 Retrieval Evaluation",
        "## Dataset",
        "## Recall",
        "## Top-K",
        "## Score distribution",
        "## Threshold analysis",
        "## Language results",
        "## No-answer results",
        "## Security verification",
        "NO_ANSWER_CASES",
        "## Tests",
        "## Remaining weaknesses",
    ):
        assert heading in text
    assert report.recall[5].recall == 1.0
    assert report.no_answer_cases == 1


def test_live_openai_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LIVE_OPENAI_ENV, raising=False)
    assert live_openai_enabled() is False
    monkeypatch.setenv(LIVE_OPENAI_ENV, "1")
    assert live_openai_enabled() is True


async def test_embedding_cache_skips_inner_on_hit(tmp_path: Path) -> None:
    inner = FakeEmbeddingProvider(dimension=8)
    cache = tmp_path / "cache.json"
    first = CachedEmbeddingProvider(
        inner, cache, model="fake-test", allow_network=True
    )
    vector = await first.embed("alpha")
    second_inner = FakeEmbeddingProvider(dimension=8)

    async def _boom(texts):
        raise AssertionError("inner must not be called on cache hit")

    second_inner.embed_batch = _boom  # type: ignore[method-assign]
    second = CachedEmbeddingProvider(
        second_inner, cache, model="fake-test", allow_network=False
    )
    cached = await second.embed("alpha")
    assert cached == vector
    assert second.network_batches == 0


async def test_embedding_cache_refuses_network_on_miss(tmp_path: Path) -> None:
    inner = FakeEmbeddingProvider(dimension=8)
    cache = CachedEmbeddingProvider(
        inner, tmp_path / "empty.json", model="fake-test", allow_network=False
    )
    with pytest.raises(ValidationError, match="cache miss"):
        await cache.embed("uncached text")


def test_threshold_candidates_cover_requested_range() -> None:
    assert THRESHOLD_CANDIDATES[0] == 0.20
    assert THRESHOLD_CANDIDATES[-1] == 0.90
    assert 0.25 in THRESHOLD_CANDIDATES
    assert 0.55 in THRESHOLD_CANDIDATES


def test_ai8_report_marks_openai_not_measured_and_omits_queries() -> None:
    report = build_report(
        provider_name="fake",
        live_openai=False,
        outcomes=[
            _outcome(no_answer=False, top=0.9, hit5=True),
            _outcome(no_answer=True, top=0.2, hit5=False),
        ],
        chunking={"passed": True},
    )
    text = render_ai8_markdown_report(
        fake=report,
        openai=None,
        measured_at="2026-08-16",
    )
    assert "# AI-8 Real Retrieval Evaluation" in text
    assert "FakeEmbeddingProvider: **MEASURED**" in text
    assert "OpenAI `text-embedding-3-small`: **NOT MEASURED**" in text
    assert "## Dataset" in text
    assert "## Recommendation for min_score" in text
    assert "UNIQUE_QUERY_SHOULD_NOT_APPEAR" not in text
    assert report.outcomes[0].question not in text or report.outcomes[0].question == "q"
    # Placeholder question "q" is too short to assert; identity-length queries
    # must not be dumped — covered by case_id-only miss lines.
    assert "F1" in text

