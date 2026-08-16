"""AI-7 retrieval evaluation: metrics, threshold analysis, embedding cache.

Evaluation-only. Not an HTTP API, not ACL, not a production relevance threshold.
CI must use FakeEmbeddingProvider or a mocked OpenAI client. Live OpenAI is
opt-in via ``ONBOARDAI_AI7_LIVE_OPENAI=1`` and never required for pytest.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.exceptions import ValidationError
from app.services.ai.embeddings import EmbeddingProvider
from app.services.ai.retriever import RetrievalHit

LIVE_OPENAI_ENV = "ONBOARDAI_AI7_LIVE_OPENAI"
EVAL_TOP_KS = (1, 3, 5, 10)
THRESHOLD_CANDIDATES = tuple(round(0.20 + step * 0.05, 2) for step in range(15))
PRIMARY_RECALL_K = 5
CROSS_LANGUAGE_PAIRS = (
    ("ru", "en"),
    ("en", "ru"),
    ("kk", "ru"),
    ("ru", "kk"),
    ("en", "kk"),
    ("kk", "en"),
)
CACHE_PURPOSE = "synthetic-eval-cache"
_FORBIDDEN_CACHE_KEYS = frozenset(
    {
        "api_key",
        "openai_api_key",
        "authorization",
        "secret",
        "token",
        "password",
        "texts",
        "query",
        "queries",
    }
)


def live_openai_enabled() -> bool:
    return os.environ.get(LIVE_OPENAI_ENV, "").strip() == "1"


def _empty_score_stats() -> ScoreStats:
    return ScoreStats(count=0, min=None, max=None, mean=None, median=None)


@dataclass(frozen=True, slots=True)
class ScoreStats:
    count: int
    min: float | None
    max: float | None
    mean: float | None
    median: float | None


@dataclass(frozen=True, slots=True)
class RecallAtK:
    k: int
    total: int
    hits: int
    misses: int
    recall: float


@dataclass(frozen=True, slots=True)
class ThresholdRow:
    threshold: float
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float | None
    recall: float | None
    f1: float | None


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    case_id: str
    question: str
    language: str
    cross_language: bool
    expect_no_answer: bool
    expected_keys: tuple[str, ...]
    expected_article_ids: tuple[UUID, ...]
    hit_keys: tuple[str, ...]
    hit_article_ids: tuple[UUID, ...]
    scores: tuple[float, ...]
    top_score: float | None
    exact_phrase: bool
    article_hit_at: dict[int, bool]
    expected_chunk_index: int | None
    chunk_index_hit: bool | None
    leaked_foreign_article: bool
    target_language: str | None = None
    match_score: float | None = None
    wrong_top: bool = False


@dataclass
class EvaluationReport:
    provider_name: str
    live_openai: bool
    total_cases: int
    answerable_cases: int
    no_answer_cases: int
    language_counts: dict[str, int]
    outcomes: list[CaseOutcome]
    recall: dict[int, RecallAtK]
    recall_by_language: dict[str, dict[int, RecallAtK]]
    cross_language_recall: dict[int, RecallAtK]
    exact_phrase_recall: dict[int, RecallAtK]
    paraphrase_recall: dict[int, RecallAtK]
    top_k_recall: dict[int, RecallAtK]
    score_all: ScoreStats
    score_hits: ScoreStats
    score_misses: ScoreStats
    score_no_answer: ScoreStats
    thresholds: list[ThresholdRow]
    no_answer_with_hits: int
    foreign_leaks: int
    chunking: dict[str, Any] = field(default_factory=dict)
    same_language_recall: dict[int, RecallAtK] = field(default_factory=dict)
    recall_by_pair: dict[str, dict[int, RecallAtK]] = field(default_factory=dict)
    score_true_positives: ScoreStats = field(default_factory=_empty_score_stats)
    score_false_positives: ScoreStats = field(default_factory=_empty_score_stats)
    model: str = ""
    dimension: int = 1536
    cache_hits: int = 0
    network_batches: int = 0
    embedded_texts: int = 0

    def recall_value(self, k: int) -> float:
        return self.recall[k].recall


def article_in_top_k(hits: Sequence[RetrievalHit], acceptable_ids: Sequence[UUID], k: int) -> bool:
    if not acceptable_ids or k < 1:
        return False
    allowed = set(acceptable_ids)
    for hit in hits[:k]:
        if hit.article_id in allowed:
            return True
    return False


def chunk_index_in_top_k(
    hits: Sequence[RetrievalHit],
    acceptable_ids: Sequence[UUID],
    *,
    chunk_index: int,
    k: int,
) -> bool:
    allowed = set(acceptable_ids)
    for hit in hits[:k]:
        if hit.article_id in allowed and hit.chunk_index == chunk_index:
            return True
    return False


def recall_at_k(hits_flags: Sequence[bool]) -> RecallAtK:
    total = len(hits_flags)
    hit_count = sum(1 for flag in hits_flags if flag)
    miss_count = total - hit_count
    recall = (hit_count / total) if total else 0.0
    return RecallAtK(
        k=0,
        total=total,
        hits=hit_count,
        misses=miss_count,
        recall=recall,
    )


def score_stats(values: Sequence[float]) -> ScoreStats:
    if not values:
        return ScoreStats(count=0, min=None, max=None, mean=None, median=None)
    return ScoreStats(
        count=len(values),
        min=min(values),
        max=max(values),
        mean=statistics.fmean(values),
        median=statistics.median(values),
    )


def threshold_analysis(
    outcomes: Sequence[CaseOutcome],
    *,
    k: int = PRIMARY_RECALL_K,
    candidates: Sequence[float] = THRESHOLD_CANDIDATES,
) -> list[ThresholdRow]:
    """Score-gated article retrieval. Analysis only — not a production cutoff.

    A case is predicted ANSWER when ``top_score >= threshold``.

    Answerable:
      TP — predicted ANSWER and expected article in top-k
      FN — otherwise
    No-answer:
      TN — predicted NO_ANSWER
      FP — predicted ANSWER
    Wrong-article answerable cases with score >= t count as FN (missed target),
    not FP, so precision is not inflated by treating every retrieval as success.
    Unretrieved no-answer rows with a score still count as FP (false answer).
    """
    rows: list[ThresholdRow] = []
    for threshold in candidates:
        tp = fp = fn = tn = 0
        for outcome in outcomes:
            predicted_answer = (
                outcome.top_score is not None and outcome.top_score >= threshold
            )
            if outcome.expect_no_answer:
                if predicted_answer:
                    fp += 1
                else:
                    tn += 1
                continue
            correct = outcome.article_hit_at.get(k, False)
            if predicted_answer and correct:
                tp += 1
            else:
                fn += 1
        precision = (tp / (tp + fp)) if (tp + fp) else None
        recall = (tp / (tp + fn)) if (tp + fn) else None
        if precision is not None and recall is not None and (precision + recall) > 0:
            f1 = 2 * precision * recall / (precision + recall)
        else:
            f1 = None
        rows.append(
            ThresholdRow(
                threshold=threshold,
                true_positives=tp,
                false_positives=fp,
                false_negatives=fn,
                true_negatives=tn,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )
    return rows


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _fmt_stats(stats: ScoreStats) -> str:
    if stats.count == 0:
        return "n=0"
    assert stats.min is not None and stats.max is not None
    assert stats.mean is not None and stats.median is not None
    return (
        f"n={stats.count} min={stats.min:.3f} max={stats.max:.3f} "
        f"mean={stats.mean:.3f} median={stats.median:.3f}"
    )


def _fmt_recall(item: RecallAtK) -> str:
    return f"{item.recall:.3f} ({item.hits}/{item.total}, misses={item.misses})"


def render_markdown_report(report: EvaluationReport) -> str:
    lines = [
        "# AI-7 Retrieval Evaluation",
        "",
        "Evaluation only. Production `min_score` remains unset. No LLM, no chat",
        "API, no Telegram AI. Numbers below are measured, not assumed.",
        "",
        f"- Provider: `{report.provider_name}`",
        f"- Live OpenAI: `{report.live_openai}`",
        "",
        "## Dataset",
        f"- number of cases: {report.total_cases}",
        f"- answerable: {report.answerable_cases}",
        f"- no-answer cases: {report.no_answer_cases}",
        f"- RU: {report.language_counts.get('ru', 0)}",
        f"- KK: {report.language_counts.get('kk', 0)}",
        f"- EN: {report.language_counts.get('en', 0)}",
        "",
        "## Recall",
    ]
    for k in (1, 3, 5):
        item = report.recall[k]
        lines.append(f"- Recall@{k}: {_fmt_recall(item)}")
    lines.extend(["", "## Top-K", ""])
    for k in EVAL_TOP_KS:
        item = report.top_k_recall[k]
        lines.append(f"- Recall@{k}: {_fmt_recall(item)}")
    r3 = report.top_k_recall[3].recall
    r5 = report.top_k_recall[5].recall
    delta = r5 - r3
    lines.extend(
        [
            "",
            f"Recall@5 minus Recall@3: {delta:+.3f}.",
            (
                "Recall@5 improves over Recall@3."
                if delta > 0.02
                else "Recall@5 does not meaningfully improve over Recall@3 "
                "(delta ≤ 0.02). Production default `top_k` is unchanged."
            ),
            "",
            "## Score distribution",
            f"- all top scores: {_fmt_stats(report.score_all)}",
            f"- hits (answerable, article in top-5): {_fmt_stats(report.score_hits)}",
            f"- misses (answerable, article not in top-5): {_fmt_stats(report.score_misses)}",
            f"- no-answer: {_fmt_stats(report.score_no_answer)}",
            "",
            "## Threshold analysis",
            "",
            "Predicted ANSWER iff top score ≥ candidate. Production threshold is",
            "**not** enabled. No candidate is auto-selected.",
            "",
            "| threshold | TP | FP | FN | TN | precision | recall | F1 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in report.thresholds:
        lines.append(
            f"| {row.threshold:.2f} | {row.true_positives} | {row.false_positives} | "
            f"{row.false_negatives} | {row.true_negatives} | "
            f"{_fmt_ratio(row.precision)} | {_fmt_ratio(row.recall)} | "
            f"{_fmt_ratio(row.f1)} |"
        )
    lines.extend(["", "## Language results", ""])
    for lang in ("ru", "kk", "en"):
        grouped = report.recall_by_language.get(lang, {})
        if 5 in grouped:
            lines.append(f"- {lang.upper()} Recall@5: {_fmt_recall(grouped[5])}")
        else:
            lines.append(f"- {lang.upper()} Recall@5: n/a")
    if report.same_language_recall:
        lines.append(
            f"- same-language Recall@5: {_fmt_recall(report.same_language_recall[5])}"
        )
    lines.append(
        f"- cross-language Recall@5: {_fmt_recall(report.cross_language_recall[5])}"
    )
    if report.recall_by_pair:
        for pair_key in (f"{src}→{dst}" for src, dst in CROSS_LANGUAGE_PAIRS):
            grouped = report.recall_by_pair.get(pair_key, {})
            if 5 in grouped:
                lines.append(f"- {pair_key} Recall@5: {_fmt_recall(grouped[5])}")
    lines.extend(
        [
            "",
            "## Exact-phrase vs paraphrase (answerable)",
            f"- exact-phrase Recall@5: {_fmt_recall(report.exact_phrase_recall[5])}",
            f"- paraphrase Recall@5: {_fmt_recall(report.paraphrase_recall[5])}",
            "",
            "## Chunking results",
        ]
    )
    if report.chunking:
        for key, value in report.chunking.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- see chunking evaluation tests")
    lines.extend(
        [
            "",
            "## No-answer results",
            f"- NO_ANSWER_CASES: {report.no_answer_cases}",
            f"- no-answer cases that still returned retrieval hits: "
            f"{report.no_answer_with_hits}",
            "",
            "Without a production `min_score`, the retriever returns the nearest",
            "allowed chunks whenever the tenant corpus is non-empty. Hits on",
            "no-answer questions are expected until a threshold is chosen in a",
            "later stage.",
            "",
            "## Misses (answerable, article not in top-5)",
            "",
        ]
    )
    misses = [
        item
        for item in report.outcomes
        if not item.expect_no_answer and not item.article_hit_at.get(5, False)
    ]
    if not misses:
        lines.append("- none")
    else:
        for item in misses:
            top_key = item.hit_keys[0] if item.hit_keys else "(empty)"
            score = f"{item.top_score:.3f}" if item.top_score is not None else "n/a"
            lines.append(
                f"- `{item.case_id}` lang={item.language} "
                f"cross={item.cross_language} expected={list(item.expected_keys)} "
                f"top={top_key} score={score}"
            )
    lines.extend(
        [
            "",
            "## Security verification",
            f"- foreign-tenant article leaks: {report.foreign_leaks}",
            "",
            "## Tests",
            "",
            "See `tests/ai/test_eval_*.py` and",
            "`tests/security/test_ai_eval_tenant_isolation.py`.",
            "",
            "## Remaining weaknesses",
            "",
            "- FakeEmbeddingProvider is a hash, not a semantic model. Paraphrase",
            "  and cross-language Recall@K are not production quality.",
            "- Without `min_score`, every no-answer query still returns nearest",
            "  neighbors from the allowed tenant corpus.",
            "- Hit vs miss vs no-answer scores overlap under fake embeddings;",
            "  threshold candidates cannot be calibrated from this provider.",
            "- Live OpenAI numbers require an explicit opt-in run and are not",
            "  part of CI.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def build_report(
    *,
    provider_name: str,
    live_openai: bool,
    outcomes: Sequence[CaseOutcome],
    chunking: dict[str, Any] | None = None,
    model: str = "",
    dimension: int = 1536,
    cache_hits: int = 0,
    network_batches: int = 0,
    embedded_texts: int = 0,
) -> EvaluationReport:
    language_counts: dict[str, int] = {}
    for outcome in outcomes:
        language_counts[outcome.language] = language_counts.get(outcome.language, 0) + 1

    answerable = [item for item in outcomes if not item.expect_no_answer]
    no_answer = [item for item in outcomes if item.expect_no_answer]

    def _recall_map(subset: Sequence[CaseOutcome]) -> dict[int, RecallAtK]:
        result: dict[int, RecallAtK] = {}
        for k in EVAL_TOP_KS:
            flags = [item.article_hit_at.get(k, False) for item in subset]
            measured = recall_at_k(flags)
            result[k] = RecallAtK(
                k=k,
                total=measured.total,
                hits=measured.hits,
                misses=measured.misses,
                recall=measured.recall,
            )
        return result

    recall = _recall_map(answerable)
    by_language: dict[str, dict[int, RecallAtK]] = {}
    for lang in ("ru", "kk", "en"):
        subset = [item for item in answerable if item.language == lang]
        if subset:
            by_language[lang] = _recall_map(subset)
    cross = [item for item in answerable if item.cross_language]
    same_language = [item for item in answerable if not item.cross_language]
    exact = [item for item in answerable if item.exact_phrase]
    paraphrase = [item for item in answerable if not item.exact_phrase]
    recall_by_pair: dict[str, dict[int, RecallAtK]] = {}
    for src, dst in CROSS_LANGUAGE_PAIRS:
        subset = [
            item
            for item in answerable
            if item.cross_language
            and item.language == src
            and item.target_language == dst
        ]
        if subset:
            recall_by_pair[f"{src}→{dst}"] = _recall_map(subset)

    hit_scores = [
        item.top_score
        for item in answerable
        if item.top_score is not None and item.article_hit_at.get(PRIMARY_RECALL_K, False)
    ]
    true_positive_scores = [
        item.match_score if item.match_score is not None else item.top_score
        for item in answerable
        if item.article_hit_at.get(PRIMARY_RECALL_K, False)
        and (item.match_score is not None or item.top_score is not None)
    ]
    false_positive_scores = [
        item.top_score
        for item in outcomes
        if item.top_score is not None and item.wrong_top
    ]
    miss_scores = [
        item.top_score
        for item in answerable
        if item.top_score is not None and not item.article_hit_at.get(PRIMARY_RECALL_K, False)
    ]
    no_answer_scores = [item.top_score for item in no_answer if item.top_score is not None]
    all_scores = [item.top_score for item in outcomes if item.top_score is not None]

    return EvaluationReport(
        provider_name=provider_name,
        live_openai=live_openai,
        total_cases=len(outcomes),
        answerable_cases=len(answerable),
        no_answer_cases=len(no_answer),
        language_counts=language_counts,
        outcomes=list(outcomes),
        recall=recall,
        recall_by_language=by_language,
        cross_language_recall=_recall_map(cross) if cross else _recall_map([]),
        exact_phrase_recall=_recall_map(exact) if exact else _recall_map([]),
        paraphrase_recall=_recall_map(paraphrase) if paraphrase else _recall_map([]),
        top_k_recall=_recall_map(answerable),
        score_all=score_stats(all_scores),
        score_hits=score_stats(hit_scores),
        score_misses=score_stats(miss_scores),
        score_no_answer=score_stats(no_answer_scores),
        thresholds=threshold_analysis(outcomes, k=PRIMARY_RECALL_K),
        no_answer_with_hits=sum(1 for item in no_answer if item.scores),
        foreign_leaks=sum(1 for item in outcomes if item.leaked_foreign_article),
        chunking=chunking or {},
        same_language_recall=_recall_map(same_language) if same_language else _recall_map([]),
        recall_by_pair=recall_by_pair,
        score_true_positives=score_stats(true_positive_scores),
        score_false_positives=score_stats(false_positive_scores),
        model=model or provider_name,
        dimension=dimension,
        cache_hits=cache_hits,
        network_batches=network_batches,
        embedded_texts=embedded_texts,
    )


def cache_key(model: str, text: str) -> str:
    payload = f"{model}\0{text}".encode()
    return hashlib.sha256(payload).hexdigest()


def eval_cache_path(root: Path, model: str) -> Path:
    """Model-specific cache file so fake and OpenAI vectors never overwrite."""
    safe = "".join(
        char if char.isalnum() or char in "._-" else "_" for char in model.strip()
    )
    if not safe:
        safe = "unknown"
    return root / ".ai7_embedding_cache" / f"{safe}.json"


def _reject_secret_cache_keys(raw: dict[str, Any]) -> None:
    for key in raw:
        if str(key).lower() in _FORBIDDEN_CACHE_KEYS:
            raise ValidationError("embedding cache must not contain secrets")


class CachedEmbeddingProvider:
    """Disk cache around an inner provider. Does not log text or API keys.

    When ``allow_network`` is false, a cache miss raises instead of calling the
    inner provider. CI uses this so OpenAI cannot be reached accidentally.
    Vectors here are evaluation-only; they are not a production KB index.
    """

    def __init__(
        self,
        inner: EmbeddingProvider,
        cache_path: Path,
        *,
        model: str,
        allow_network: bool,
    ) -> None:
        self._inner = inner
        self._cache_path = cache_path
        self._model = model
        self._allow_network = allow_network
        self._vectors: dict[str, list[float]] = {}
        self._load()

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    @property
    def model(self) -> str:
        return self._model

    @property
    def cache_hits(self) -> int:
        return self._cache_hit_count

    @property
    def network_batches(self) -> int:
        return self._network_batches

    @property
    def embedded_texts(self) -> int:
        return self._embedded_texts

    def _load(self) -> None:
        self._cache_hit_count = 0
        self._network_batches = 0
        self._embedded_texts = 0
        if not self._cache_path.is_file():
            return
        raw = json.loads(self._cache_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValidationError("embedding cache is invalid")
        _reject_secret_cache_keys(raw)
        stored_model = raw.get("model")
        stored_dim = raw.get("dimension")
        vectors = raw.get("vectors")
        if stored_model != self._model:
            return
        if stored_dim != self._inner.dimension:
            return
        if not isinstance(vectors, dict):
            raise ValidationError("embedding cache is invalid")
        for key, value in vectors.items():
            if not isinstance(key, str) or not isinstance(value, list):
                continue
            if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
                continue
            if len(value) != self._inner.dimension:
                continue
            self._vectors[key] = [float(component) for component in value]

    def _save(self) -> None:
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "purpose": CACHE_PURPOSE,
            "not_a_kb_index": True,
            "model": self._model,
            "dimension": self._inner.dimension,
            "vectors": self._vectors,
        }
        serialized = json.dumps(payload, separators=(",", ":"))
        if any(
            needle in serialized.lower()
            for needle in ("sk-", "api_key", "bearer ")
        ):
            raise ValidationError("embedding cache refused to persist secrets")
        self._cache_path.write_text(serialized, encoding="utf-8")

    async def embed(self, text: str) -> list[float]:
        vectors = await self.embed_batch((text,))
        return vectors[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, str | bytes):
            raise ValidationError("texts must be a sequence of strings, not a single string")
        if not isinstance(texts, Sequence):
            raise ValidationError("texts must be a sequence of strings")
        if not texts:
            return []
        keys = [cache_key(self._model, text) for text in texts]
        self._embedded_texts += len(texts)
        missing_texts: list[str] = []
        missing_keys: list[str] = []
        seen_missing: set[str] = set()
        for text, key in zip(texts, keys, strict=True):
            if key in self._vectors:
                self._cache_hit_count += 1
                continue
            if key in seen_missing:
                continue
            seen_missing.add(key)
            missing_texts.append(text)
            missing_keys.append(key)
        if missing_texts:
            if not self._allow_network:
                raise ValidationError(
                    "embedding cache miss; live network is disabled for AI-7 CI"
                )
            fetched = await self._inner.embed_batch(missing_texts)
            self._network_batches += 1
            if len(fetched) != len(missing_texts):
                raise ValidationError("embedding batch size does not match chunks")
            for key, vector in zip(missing_keys, fetched, strict=True):
                if len(vector) != self._inner.dimension:
                    raise ValidationError(
                        "embedding dimension mismatch: expected "
                        f"{self._inner.dimension}, got {len(vector)}"
                    )
                if not all(math.isfinite(component) for component in vector):
                    raise ValidationError("embedding provider returned an invalid vector")
                self._vectors[key] = list(vector)
            self._save()
        return [self._vectors[key] for key in keys]


def _fmt_report_recall(report: EvaluationReport | None, k: int) -> str:
    if report is None:
        return "NOT MEASURED"
    return _fmt_recall(report.recall[k])


def recommend_top_k(report: EvaluationReport) -> str:
    r3 = report.top_k_recall[3].recall
    r5 = report.top_k_recall[5].recall
    r10 = report.top_k_recall[10].recall
    delta_53 = r5 - r3
    delta_105 = r10 - r5
    parts = [
        f"Recall@1={report.top_k_recall[1].recall:.3f}, "
        f"Recall@3={r3:.3f}, Recall@5={r5:.3f}, Recall@10={r10:.3f}."
    ]
    if delta_53 > 0.02:
        parts.append("Recall@5 materially improves on Recall@3.")
    else:
        parts.append("Recall@5 does not materially improve on Recall@3 (delta ≤ 0.02).")
    if delta_105 > 0.05:
        parts.append(
            "Recall@10 is higher than Recall@5. Inspect remaining misses before "
            "raising production `top_k`. Production default remains 5."
        )
    else:
        parts.append(
            "Raising K above 5 does not materially improve recall on this set. "
            "Keep production `top_k=5`."
        )
    parts.append("This stage does not change the production default.")
    return " ".join(parts)


def recommend_min_score(report: EvaluationReport) -> str:
    hits = report.score_true_positives
    absent = report.score_no_answer
    if hits.count == 0 or absent.count == 0 or hits.min is None or absent.max is None:
        return (
            "Keep production `min_score` unset. This run does not show a "
            "calibrated gap between answerable hits and no-answer scores."
        )
    separated = absent.max < hits.min
    strong = [
        row
        for row in report.thresholds
        if row.precision is not None
        and row.recall is not None
        and row.f1 is not None
        and row.precision >= 0.85
        and row.recall >= 0.70
    ]
    if separated and strong:
        best = max(strong, key=lambda row: row.f1 or 0.0)
        return (
            f"On this synthetic set, no-answer max={absent.max:.3f} sits below "
            f"true-positive min={hits.min:.3f}. Candidate {best.threshold:.2f} "
            f"has precision={best.precision:.3f} recall={best.recall:.3f} "
            f"F1={best.f1:.3f}. Do **not** enable it in production automatically; "
            "re-measure on a larger held-out set first."
        )
    return (
        "Keep production `min_score` unset. Answerable-hit and no-answer "
        "score distributions overlap on this corpus, so a cutoff would trade "
        "recall for incomplete no-answer rejection."
    )


def _miss_lines(report: EvaluationReport) -> list[str]:
    misses = [
        item
        for item in report.outcomes
        if not item.expect_no_answer and not item.article_hit_at.get(5, False)
    ]
    if not misses:
        return ["- none"]
    lines: list[str] = []
    for item in misses:
        top_key = item.hit_keys[0] if item.hit_keys else "(empty)"
        score = f"{item.top_score:.3f}" if item.top_score is not None else "n/a"
        lines.append(
            f"- `{item.case_id}` lang={item.language} "
            f"cross={item.cross_language} expected={list(item.expected_keys)} "
            f"top={top_key} score={score}"
        )
    return lines


def _language_lines(report: EvaluationReport) -> list[str]:
    lines: list[str] = []
    for lang in ("ru", "kk", "en"):
        grouped = report.recall_by_language.get(lang, {})
        if 5 in grouped:
            lines.append(f"- {lang.upper()} Recall@5: {_fmt_recall(grouped[5])}")
        else:
            lines.append(f"- {lang.upper()} Recall@5: n/a")
    if report.same_language_recall:
        lines.append(
            f"- same-language Recall@5: {_fmt_recall(report.same_language_recall[5])}"
        )
    lines.append(
        f"- cross-language Recall@5: {_fmt_recall(report.cross_language_recall[5])}"
    )
    for src, dst in CROSS_LANGUAGE_PAIRS:
        key = f"{src}→{dst}"
        grouped = report.recall_by_pair.get(key, {})
        if 5 in grouped:
            lines.append(f"- {key} Recall@5: {_fmt_recall(grouped[5])}")
        else:
            lines.append(f"- {key} Recall@5: n/a (no cases)")
    return lines


def _threshold_table(report: EvaluationReport) -> list[str]:
    lines = [
        "| threshold | TP | FP | FN | TN | precision | recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.thresholds:
        lines.append(
            f"| {row.threshold:.2f} | {row.true_positives} | {row.false_positives} | "
            f"{row.false_negatives} | {row.true_negatives} | "
            f"{_fmt_ratio(row.precision)} | {_fmt_ratio(row.recall)} | "
            f"{_fmt_ratio(row.f1)} |"
        )
    return lines


def render_ai8_markdown_report(
    *,
    fake: EvaluationReport,
    openai: EvaluationReport | None,
    measured_at: str | None = None,
) -> str:
    """Combined Fake vs OpenAI evaluation. Never invents OpenAI numbers."""
    stamp = measured_at or "unspecified"
    openai_status = "MEASURED" if openai is not None else "NOT MEASURED"
    lines = [
        "# AI-8 Real Retrieval Evaluation",
        "",
        "Evaluation only. Production `min_score` remains unset. Production",
        "`top_k` remains 5. No LLM, no chat API, no Telegram AI.",
        "",
        "Labels:",
        "",
        "- **MEASURED** — numbers produced by an actual evaluation run",
        "- **NOT MEASURED** — the live OpenAI path was not executed; do not",
        "  invent or copy FakeEmbeddingProvider scores as OpenAI quality",
        "",
        f"- Generated: `{stamp}`",
        f"- FakeEmbeddingProvider: **MEASURED** (`{fake.provider_name}`)",
        f"- OpenAI `text-embedding-3-small`: **{openai_status}**",
        "",
        "## Dataset",
        "",
        "Synthetic corpus in `app/services/ai/eval_corpus.py`. No production",
        "employee PII, no live tenant data, no secrets.",
        "",
        f"- number of cases: {fake.total_cases}",
        f"- answerable: {fake.answerable_cases}",
        f"- no-answer cases: {fake.no_answer_cases}",
        f"- RU: {fake.language_counts.get('ru', 0)}",
        f"- KK: {fake.language_counts.get('kk', 0)}",
        f"- EN: {fake.language_counts.get('en', 0)}",
        f"- cross-language (answerable): {fake.cross_language_recall[5].total}",
        f"- exact-identity: {fake.exact_phrase_recall[5].total}",
        f"- paraphrase (answerable): {fake.paraphrase_recall[5].total}",
        "",
        "## Model",
        "",
        "- Fake provider: in-process SHA-256 hash embeddings (not semantic)",
        "- OpenAI model: `text-embedding-3-small`",
        "",
        "## Dimensions",
        "",
        f"- pgvector column / evaluation width: `{fake.dimension}`",
        "- OpenAI native width: `1536`",
        "",
        "## Evaluation methodology",
        "",
        "1. Seed Company A + Company B articles through `ArticleService`",
        "   (publish → post-commit index). Company B holds a unique bonus",
        "   article that must never appear in Company A hits.",
        "2. Query the production `KnowledgeRetriever` as a Company A employee.",
        "3. Authorization path is unchanged:",
        "   AUTH → TENANT → EMPLOYEE → PUBLISHED → VISIBILITY → PROGRAM ACL",
        "   → RETRIEVAL.",
        "4. Article-level hit: an acceptable `article_id` appears in top-k.",
        "5. CI / pytest uses FakeEmbeddingProvider or a mocked HTTP client.",
        "   Live OpenAI requires `ONBOARDAI_AI7_LIVE_OPENAI=1` and",
        "   `--live-openai` plus `AI_EMBEDDING_API_KEY` or `OPENAI_API_KEY`.",
        "6. Embeddings are batched and cached under `.ai7_embedding_cache/`",
        "   (gitignored, model-specific JSON, hash keys only, no API keys,",
        "   no raw query text, `not_a_kb_index=true`).",
        "",
        "## Fake results",
        "",
        "**MEASURED** against FakeEmbeddingProvider. Hash embeddings are not",
        "semantic — do not use these scores to choose production thresholds",
        "or to claim RU/KK/EN quality.",
        "",
        f"- Recall@1: {_fmt_recall(fake.recall[1])}",
        f"- Recall@3: {_fmt_recall(fake.recall[3])}",
        f"- Recall@5: {_fmt_recall(fake.recall[5])}",
        f"- Recall@10: {_fmt_recall(fake.recall[10])}",
        f"- exact-identity Recall@5: {_fmt_recall(fake.exact_phrase_recall[5])}",
        f"- paraphrase Recall@5: {_fmt_recall(fake.paraphrase_recall[5])}",
        f"- foreign-tenant leaks: {fake.foreign_leaks}",
        "",
        "## OpenAI results",
        "",
    ]
    if openai is None:
        lines.extend(
            [
                "**NOT MEASURED.** Live `text-embedding-3-small` evaluation was",
                "not executed in this document generation. Run:",
                "",
                "```",
                "ONBOARDAI_AI7_LIVE_OPENAI=1 python -m scripts.evaluate_kb_retrieval "
                "--live-openai --write-report",
                "```",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "**MEASURED** against OpenAI `text-embedding-3-small` (1536-d).",
                "Numbers below are from the live opt-in run (or its embedding cache).",
                "",
                f"- model: `{openai.model}`",
                f"- dimension: `{openai.dimension}`",
                f"- live_openai: `{openai.live_openai}`",
                f"- cache hits: {openai.cache_hits}",
                f"- network batches: {openai.network_batches}",
                f"- embedded texts (including cache hits): {openai.embedded_texts}",
                f"- Recall@1: {_fmt_recall(openai.recall[1])}",
                f"- Recall@3: {_fmt_recall(openai.recall[3])}",
                f"- Recall@5: {_fmt_recall(openai.recall[5])}",
                f"- Recall@10: {_fmt_recall(openai.recall[10])}",
                f"- exact-identity Recall@5: {_fmt_recall(openai.exact_phrase_recall[5])}",
                f"- paraphrase Recall@5: {_fmt_recall(openai.paraphrase_recall[5])}",
                f"- foreign-tenant leaks: {openai.foreign_leaks}",
                "",
            ]
        )
    lines.extend(
        [
            "## Recall@K",
            "",
            "| k | Fake (MEASURED) | OpenAI |",
            "|---:|---|---|",
        ]
    )
    for k in EVAL_TOP_KS:
        lines.append(
            f"| {k} | {_fmt_recall(fake.recall[k])} | {_fmt_report_recall(openai, k)} |"
        )
    lines.extend(["", "## Score distributions", ""])
    if openai is None:
        lines.extend(
            [
                "OpenAI score distributions: **NOT MEASURED**.",
                "",
                "Fake (MEASURED, not semantic):",
                f"- true positives: {_fmt_stats(fake.score_true_positives)}",
                f"- false positives (wrong top-1 or no-answer hits): "
                f"{_fmt_stats(fake.score_false_positives)}",
                f"- misses: {_fmt_stats(fake.score_misses)}",
                f"- no-answer: {_fmt_stats(fake.score_no_answer)}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "OpenAI (**MEASURED**):",
                f"- true positives: {_fmt_stats(openai.score_true_positives)}",
                f"- false positives (wrong top-1 or no-answer hits): "
                f"{_fmt_stats(openai.score_false_positives)}",
                f"- misses: {_fmt_stats(openai.score_misses)}",
                f"- no-answer: {_fmt_stats(openai.score_no_answer)}",
                "",
                "Fake (**MEASURED**, not semantic, not for calibration):",
                f"- true positives: {_fmt_stats(fake.score_true_positives)}",
                f"- false positives: {_fmt_stats(fake.score_false_positives)}",
                f"- misses: {_fmt_stats(fake.score_misses)}",
                f"- no-answer: {_fmt_stats(fake.score_no_answer)}",
                "",
            ]
        )
    lines.extend(["## Threshold analysis", ""])
    if openai is None:
        lines.extend(
            [
                "OpenAI thresholds: **NOT MEASURED**. Fake thresholds below are",
                "shown for pipeline completeness only — do not pick a production",
                "`min_score` from hash embeddings.",
                "",
                *(_threshold_table(fake)),
                "",
                f"**Recommendation (Fake):** {recommend_min_score(fake)}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "Predicted ANSWER iff top score ≥ candidate. Analysis only —",
                "production `min_score` is **not** enabled by this table.",
                "",
                "OpenAI (**MEASURED**):",
                "",
                *(_threshold_table(openai)),
                "",
                f"**Recommendation (OpenAI):** {recommend_min_score(openai)}",
                "",
            ]
        )
    lines.extend(["## Multilingual analysis", ""])
    if openai is None:
        lines.extend(
            [
                "OpenAI RU/KK/EN and cross-language quality: **NOT MEASURED**.",
                "Do not claim multilingual quality from FakeEmbeddingProvider.",
                "",
                "Fake query-language Recall@5 (MEASURED, not semantic):",
                "",
                *(_language_lines(fake)),
                "",
            ]
        )
    else:
        lines.extend(
            [
                "OpenAI (**MEASURED**). This is the only provider that may be",
                "used to judge Kazakh and cross-language retrieval quality.",
                "",
                *(_language_lines(openai)),
                "",
                "Fake (MEASURED, hash, not semantic — do not cite as quality):",
                "",
                *(_language_lines(fake)),
                "",
            ]
        )
    lines.extend(["## No-answer analysis", ""])
    if openai is None:
        lines.extend(
            [
                "OpenAI no-answer behavior: **NOT MEASURED**.",
                "",
                f"- Fake NO_ANSWER_CASES: {fake.no_answer_cases}",
                f"- Fake no-answer cases that still returned hits: "
                f"{fake.no_answer_with_hits}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                f"- OpenAI NO_ANSWER_CASES: {openai.no_answer_cases}",
                f"- OpenAI no-answer cases that still returned hits: "
                f"{openai.no_answer_with_hits}",
                f"- OpenAI no-answer scores: {_fmt_stats(openai.score_no_answer)}",
                f"- OpenAI answerable-hit scores: {_fmt_stats(openai.score_true_positives)}",
                "",
                "Without a production `min_score`, the retriever still returns",
                "nearest allowed chunks whenever the tenant corpus is non-empty.",
                "",
            ]
        )
    lines.extend(["## Chunking observations", ""])
    source = openai or fake
    if source.chunking:
        for key, value in source.chunking.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- see chunking evaluation tests")
    lines.extend(
        [
            "",
            "The character-window chunker was not redesigned in AI-8.",
            "Concrete OpenAI misses (if any) are listed below; a chunking",
            "change requires evidence that a window split hid the answer.",
            "",
            "### Answerable misses (article not in top-5)",
            "",
        ]
    )
    if openai is None:
        lines.append("OpenAI misses: **NOT MEASURED**.")
        lines.append("")
        lines.append("Fake misses (MEASURED, not semantic):")
        lines.extend(_miss_lines(fake))
    else:
        lines.append("OpenAI (**MEASURED**):")
        lines.extend(_miss_lines(openai))
    lines.extend(
        [
            "",
            "## Security results",
            "",
            f"- Fake foreign-tenant article leaks: {fake.foreign_leaks}",
            (
                f"- OpenAI foreign-tenant article leaks: {openai.foreign_leaks}"
                if openai is not None
                else "- OpenAI foreign-tenant article leaks: NOT MEASURED"
            ),
            "",
            "ACL tests (pytest, FakeEmbeddingProvider) continue to prove:",
            "",
            "- Company A cannot retrieve Company B",
            "- UUID probing cannot expose B",
            "- B's exact text cannot retrieve B through A",
            "- metadata poisoning does not bypass ACL",
            "- historical / draft / archived versions are not retrieved",
            "- program visibility still respects assignment",
            "- cancelled assignments remain inaccessible",
            "- Super Admin remains forbidden without tenant impersonation",
            "",
            "`ArticleService` remains the only KB authorization authority.",
            "",
            "## Cost / operational observations",
            "",
        ]
    )
    if openai is None:
        lines.extend(
            [
                "**NOT MEASURED** for live OpenAI. Fake evaluation does not",
                "call the network.",
                "",
                f"- Fake cache hits: {fake.cache_hits}",
                f"- Fake network batches (in-process provider): {fake.network_batches}",
                "",
            ]
        )
    else:
        approx_cost = (
            "Live batch count is the number of OpenAI `/v1/embeddings` calls "
            "after cache. `text-embedding-3-small` is billed per token "
            "(approximately $0.02 / 1M tokens); this corpus is tens of "
            "short policy texts plus 42 queries, so a cold run is typically "
            "well under one cent. Repeated runs are cache-deterministic and "
            "issue no new HTTP calls when the cache is warm."
        )
        lines.extend(
            [
                "**MEASURED** operational counters (not a billing invoice):",
                "",
                f"- cache hits: {openai.cache_hits}",
                f"- network batches: {openai.network_batches}",
                f"- embedded texts: {openai.embedded_texts}",
                "",
                approx_cost,
                "",
            ]
        )
    lines.extend(["## Recommendation for top_k", ""])
    if openai is None:
        lines.extend(
            [
                "OpenAI top-k recommendation: **NOT MEASURED**. Fake top-k is",
                "not a production signal.",
                "",
                f"Fake (not for production): {recommend_top_k(fake)}",
                "",
                "Production default `top_k=5` is unchanged.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                recommend_top_k(openai),
                "",
            ]
        )
    lines.extend(["## Recommendation for min_score", ""])
    if openai is None:
        lines.extend(
            [
                "OpenAI `min_score` recommendation: **NOT MEASURED**.",
                "Do not choose a production threshold from FakeEmbeddingProvider.",
                "",
                f"Fake (not for production): {recommend_min_score(fake)}",
                "",
            ]
        )
    else:
        lines.extend([recommend_min_score(openai), ""])
    lines.extend(
        [
            "## Known limitations",
            "",
            "- Dataset is synthetic and small (42 cases). Pair cells such as",
            "  RU→EN may have n=1; treat pair recall as directional, not a",
            "  population estimate.",
            "- FakeEmbeddingProvider is a hash. Paraphrase and cross-language",
            "  Fake Recall@K are not production quality.",
            "- Live OpenAI is opt-in, cached, and never part of pytest/CI.",
            "- Without `min_score`, no-answer queries still return neighbors.",
            "- No LLM, no citations runtime, no `/ai/chat` or `/ai/search`.",
            "- Evaluation tenants are created and deleted by the script; they",
            "  are not production companies.",
            "",
            "## Tests",
            "",
            "See `tests/ai/test_eval_*.py`, `tests/ai/test_openai_embeddings.py`,",
            "`tests/security/test_ai_retrieval_acl.py`, and",
            "`tests/security/test_ai_eval_tenant_isolation.py`.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"
