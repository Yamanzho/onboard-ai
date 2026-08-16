"""AI-8 end-to-end RAG evaluation metrics. Evaluation-only — not ACL, not RAG.

Scores answers from the existing AIChatService. Does not change retrieval,
prompts, top_k, min_score, or providers. Live OpenAI is never required.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.ai_constants import DEFAULT_RETRIEVAL_TOP_K
from app.services.ai.eval_corpus import articles_by_key

ROOT = Path(__file__).resolve().parents[3]
DATASET_PATH = ROOT / "tests" / "ai" / "evaluation" / "dataset.json"
DEFAULT_REPORT_MD = ROOT / "docs" / "ai" / "ai8-rag-evaluation.md"
DEFAULT_REPORT_JSON = ROOT / "docs" / "ai" / "ai8-rag-evaluation.json"

SCORE_INCORRECT = 0
SCORE_PARTIAL = 1
SCORE_CORRECT = 2


@dataclass(frozen=True, slots=True)
class RagEvalCase:
    id: str
    question: str
    language: str
    categories: tuple[str, ...]
    expected_answerable: bool
    expected_sources: tuple[str, ...]
    expected_behavior: str
    must_contain_any: tuple[tuple[str, ...], ...]
    forbidden_substrings: tuple[str, ...]
    evaluation_notes: str


@dataclass(frozen=True, slots=True)
class LatencyStats:
    n: int
    min_ms: float | None
    p50_ms: float | None
    p95_ms: float | None
    max_ms: float | None


@dataclass(frozen=True, slots=True)
class ScoreHistogram:
    incorrect: int
    partial: int
    correct: int
    mean: float | None


@dataclass(frozen=True, slots=True)
class NoAnswerStats:
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float | None
    recall: float | None


@dataclass(frozen=True, slots=True)
class SecurityCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True, slots=True)
class CaseScore:
    case_id: str
    question: str
    categories: tuple[str, ...]
    expected_answerable: bool
    expected_behavior: str
    no_answer: bool
    retrieval_hit: bool
    retrieved_keys: tuple[str, ...]
    cited_keys: tuple[str, ...]
    correctness: int
    groundedness: int
    citation: int
    leaked_forbidden: bool
    latency_ms: float
    answer_preview: str
    notes: str


@dataclass(frozen=True, slots=True)
class RagEvalReport:
    measured_at: str
    live_openai: bool
    embedding_provider: str
    llm_provider: str
    llm_model: str
    top_k: int
    dataset_size: int
    categories: dict[str, int]
    retrieval_recall_at_k: float | None
    source_hit_rate: float | None
    answer: ScoreHistogram
    groundedness: ScoreHistogram
    citation: ScoreHistogram
    no_answer: NoAnswerStats
    latency: LatencyStats
    security: tuple[SecurityCheck, ...]
    cases: tuple[CaseScore, ...]
    limitations: tuple[str, ...]
    findings: tuple[str, ...]

    @property
    def security_passed(self) -> bool:
        return all(check.passed for check in self.security)


def load_rag_eval_dataset(path: Path | None = None) -> tuple[RagEvalCase, ...]:
    target = path or DATASET_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    known = articles_by_key()
    cases: list[RagEvalCase] = []
    seen: set[str] = set()
    for raw in payload["cases"]:
        case_id = str(raw["id"])
        if case_id in seen:
            raise ValueError(f"duplicate eval case id {case_id!r}")
        seen.add(case_id)
        sources = tuple(str(item) for item in raw.get("expected_sources", []))
        for key in sources:
            if key not in known:
                raise ValueError(f"{case_id}: unknown expected source {key!r}")
        groups = tuple(
            tuple(str(item) for item in group)
            for group in raw.get("must_contain_any", [])
        )
        cases.append(
            RagEvalCase(
                id=case_id,
                question=str(raw["question"]),
                language=str(raw.get("language", "en")),
                categories=tuple(str(item) for item in raw.get("categories", ())),
                expected_answerable=bool(raw["expected_answerable"]),
                expected_sources=sources,
                expected_behavior=str(raw["expected_behavior"]),
                must_contain_any=groups,
                forbidden_substrings=tuple(
                    str(item) for item in raw.get("forbidden_substrings", [])
                ),
                evaluation_notes=str(raw.get("evaluation_notes", "")),
            )
        )
    return tuple(cases)


def contains_any(text: str, needles: Sequence[str]) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in needles if needle)


def fact_groups_hit(text: str, groups: Sequence[Sequence[str]]) -> int:
    return sum(1 for group in groups if contains_any(text, group))


def percentile(values: Sequence[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    weight = rank - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def latency_stats(values: Sequence[float]) -> LatencyStats:
    if not values:
        return LatencyStats(n=0, min_ms=None, p50_ms=None, p95_ms=None, max_ms=None)
    return LatencyStats(
        n=len(values),
        min_ms=min(values),
        p50_ms=percentile(values, 50),
        p95_ms=percentile(values, 95),
        max_ms=max(values),
    )


def histogram(scores: Sequence[int]) -> ScoreHistogram:
    if not scores:
        return ScoreHistogram(incorrect=0, partial=0, correct=0, mean=None)
    return ScoreHistogram(
        incorrect=sum(1 for item in scores if item == SCORE_INCORRECT),
        partial=sum(1 for item in scores if item == SCORE_PARTIAL),
        correct=sum(1 for item in scores if item == SCORE_CORRECT),
        mean=sum(scores) / len(scores),
    )


def no_answer_stats(cases: Sequence[CaseScore]) -> NoAnswerStats:
    quality = [item for item in cases if "security" not in item.categories]
    tp = sum(1 for item in quality if not item.expected_answerable and item.no_answer)
    fp = sum(1 for item in quality if item.expected_answerable and item.no_answer)
    fn = sum(
        1 for item in quality if not item.expected_answerable and not item.no_answer
    )
    tn = sum(1 for item in quality if item.expected_answerable and not item.no_answer)
    precision = (tp / (tp + fp)) if (tp + fp) else None
    recall = (tp / (tp + fn)) if (tp + fn) else None
    return NoAnswerStats(
        tp=tp, fp=fp, fn=fn, tn=tn, precision=precision, recall=recall
    )


def score_case(
    case: RagEvalCase,
    *,
    retrieved_keys: Sequence[str],
    cited_keys: Sequence[str],
    answer: str,
    no_answer: bool,
    latency_ms: float,
) -> CaseScore:
    retrieved = tuple(retrieved_keys)
    cited = tuple(cited_keys)
    expected = set(case.expected_sources)
    retrieval_hit = bool(expected & set(retrieved)) if expected else False
    leaked = contains_any(answer, case.forbidden_substrings)
    facts = fact_groups_hit(answer, case.must_contain_any)
    fact_total = len(case.must_contain_any)
    gold_cited = bool(expected & set(cited)) if expected else False

    if case.expected_behavior == "no_leak":
        if leaked:
            correctness = SCORE_INCORRECT
            groundedness = SCORE_INCORRECT
            citation = SCORE_INCORRECT
        elif no_answer:
            correctness = SCORE_CORRECT
            groundedness = SCORE_CORRECT
            citation = SCORE_CORRECT if not cited else SCORE_PARTIAL
        else:
            correctness = SCORE_PARTIAL
            groundedness = SCORE_PARTIAL
            citation = SCORE_INCORRECT if cited else SCORE_PARTIAL
    elif not case.expected_answerable:
        correctness = SCORE_CORRECT if no_answer else SCORE_INCORRECT
        groundedness = SCORE_CORRECT if no_answer else SCORE_INCORRECT
        citation = SCORE_CORRECT if no_answer and not cited else SCORE_INCORRECT
    elif no_answer:
        correctness = SCORE_INCORRECT
        groundedness = SCORE_INCORRECT
        citation = SCORE_INCORRECT
    else:
        if fact_total and facts == fact_total:
            correctness = SCORE_CORRECT
        elif facts or gold_cited or retrieval_hit:
            correctness = SCORE_PARTIAL
        else:
            correctness = SCORE_INCORRECT
        if gold_cited and fact_total and facts == fact_total:
            groundedness = SCORE_CORRECT
        elif cited:
            groundedness = SCORE_PARTIAL
        else:
            groundedness = SCORE_INCORRECT
        if gold_cited:
            citation = SCORE_CORRECT
        elif cited:
            citation = SCORE_PARTIAL
        else:
            citation = SCORE_INCORRECT

    preview = " ".join(answer.split())
    if len(preview) > 160:
        preview = preview[:159].rstrip() + "…"
    return CaseScore(
        case_id=case.id,
        question=case.question,
        categories=case.categories,
        expected_answerable=case.expected_answerable,
        expected_behavior=case.expected_behavior,
        no_answer=no_answer,
        retrieval_hit=retrieval_hit,
        retrieved_keys=retrieved,
        cited_keys=cited,
        correctness=correctness,
        groundedness=groundedness,
        citation=citation,
        leaked_forbidden=leaked,
        latency_ms=latency_ms,
        answer_preview=preview,
        notes=case.evaluation_notes,
    )


def _ratio(hits: int, total: int) -> float | None:
    if total <= 0:
        return None
    return hits / total


def build_rag_report(
    *,
    cases: Sequence[CaseScore],
    dataset: Sequence[RagEvalCase],
    security: Sequence[SecurityCheck],
    live_openai: bool,
    embedding_provider: str,
    llm_provider: str,
    llm_model: str,
    findings: Sequence[str] = (),
    measured_at: str | None = None,
) -> RagEvalReport:
    answerable = [item for item in cases if item.expected_answerable]
    retrieval_hits = sum(1 for item in answerable if item.retrieval_hit)
    categories: dict[str, int] = {}
    for spec in dataset:
        for label in spec.categories:
            categories[label] = categories.get(label, 0) + 1
    limitations = (
        "Small evaluation sample; results are directional and not "
        "statistically representative.",
        "P95 latency is not statistically meaningful at this sample size.",
        "FakeEmbeddingProvider is a hash, not a semantic embedding model.",
        "FakeLLMProvider emits a citation stub and is not a factual-answer "
        "quality signal for production gpt-4o-mini.",
        "Live OpenAI numbers appear only when that path actually ran.",
        f"Production top_k remains {DEFAULT_RETRIEVAL_TOP_K}; min_score remains unset.",
    )
    return RagEvalReport(
        measured_at=measured_at or datetime.now(UTC).date().isoformat(),
        live_openai=live_openai,
        embedding_provider=embedding_provider,
        llm_provider=llm_provider,
        llm_model=llm_model,
        top_k=DEFAULT_RETRIEVAL_TOP_K,
        dataset_size=len(dataset),
        categories=dict(sorted(categories.items())),
        retrieval_recall_at_k=_ratio(retrieval_hits, len(answerable)),
        source_hit_rate=_ratio(retrieval_hits, len(answerable)),
        answer=histogram([item.correctness for item in cases]),
        groundedness=histogram([item.groundedness for item in cases]),
        citation=histogram([item.citation for item in cases]),
        no_answer=no_answer_stats(cases),
        latency=latency_stats([item.latency_ms for item in cases]),
        security=tuple(security),
        cases=tuple(cases),
        limitations=limitations,
        findings=tuple(findings),
    )


def _fmt_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _fmt_ms(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f} ms"


def _fmt_hist(hist: ScoreHistogram) -> str:
    mean = "n/a" if hist.mean is None else f"{hist.mean:.3f}"
    return (
        f"correct={hist.correct}, partial={hist.partial}, "
        f"incorrect={hist.incorrect}, mean={mean}"
    )


def render_rag_markdown(report: RagEvalReport) -> str:
    live_status = "MEASURED" if report.live_openai else "NOT MEASURED"
    fake_status = "NOT MEASURED" if report.live_openai else "MEASURED"
    na = report.no_answer
    lat = report.latency
    lines = [
        "# AI-8 Evaluation Report",
        "",
        "End-to-end RAG evaluation of the existing `AIChatService` path.",
        "This stage does **not** change retrieval, embeddings, prompts,",
        "`top_k`, or `min_score`.",
        "",
        "Labels:",
        "",
        "- **MEASURED** — numbers produced by an actual evaluation run",
        "- **NOT MEASURED** — that provider path was not executed",
        "",
        f"- Generated: `{report.measured_at}`",
        f"- Fake embeddings + FakeLLM: **{fake_status}**",
        f"- Live OpenAI embeddings+LLM: **{live_status}**",
        f"- Embedding provider: `{report.embedding_provider}`",
        f"- LLM provider: `{report.llm_provider}` (`{report.llm_model}`)",
        f"- Production top_k used: `{report.top_k}`",
        "",
        "## Dataset",
        "",
        f"- cases: {report.dataset_size}",
    ]
    for label, count in report.categories.items():
        lines.append(f"- {label}: {count}")
    lines.extend(
        [
            "",
            "Corpus: synthetic articles in `app/services/ai/eval_corpus.py`.",
            "Questions: `tests/ai/evaluation/dataset.json`.",
            "",
            "## Retrieval",
            "",
            f"- Recall@{report.top_k} / source hit rate: "
            f"{_fmt_ratio(report.retrieval_recall_at_k)}",
            "",
            "Article-level hit: an expected source key appears in production",
            f"`top_k={report.top_k}` retrieval hits. Exact chunk index is not required.",
            "",
            "## Answer",
            "",
            _fmt_hist(report.answer),
            "",
            "## Groundedness",
            "",
            _fmt_hist(report.groundedness),
            "",
            "## Citation accuracy",
            "",
            _fmt_hist(report.citation),
            "",
            "## No-answer",
            "",
            f"- TP={na.tp} FP={na.fp} FN={na.fn} TN={na.tn}",
            f"- Precision: {_fmt_ratio(na.precision)}",
            f"- Recall: {_fmt_ratio(na.recall)}",
            "",
            "## Latency",
            "",
            f"- n={lat.n}",
            f"- min: {_fmt_ms(lat.min_ms)}",
            f"- P50 / median: {_fmt_ms(lat.p50_ms)}",
            f"- P95: {_fmt_ms(lat.p95_ms)}",
            f"- max: {_fmt_ms(lat.max_ms)}",
            "",
            "P95 is reported for completeness; the sample is too small for a",
            "statistically meaningful tail estimate.",
            "",
            "## Security",
            "",
            f"- overall: {'PASS' if report.security_passed else 'FAIL'}",
        ]
    )
    for check in report.security:
        mark = "PASS" if check.passed else "FAIL"
        lines.append(f"- {check.name}: {mark} — {check.detail}")
    lines.extend(["", "## Findings", ""])
    if report.findings:
        lines.extend(f"- {item}" for item in report.findings)
    else:
        lines.append("- No additional findings recorded.")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    lines.extend(
        [
            "",
            "## How to reproduce",
            "",
            "```",
            "python -m scripts.evaluate_rag --write-report",
            "```",
            "",
            "Live OpenAI (never required for pytest/CI):",
            "",
            "```",
            "ONBOARDAI_AI7_LIVE_OPENAI=1 python -m scripts.evaluate_rag "
            "--live-openai --write-report",
            "```",
            "",
            "Requires `AI_EMBEDDING_API_KEY`/`AI_LLM_API_KEY` or `OPENAI_API_KEY`.",
            "Do not commit keys. Application startup does not run this evaluation.",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def report_to_json(report: RagEvalReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["security_passed"] = report.security_passed
    payload["live_openai_status"] = (
        "MEASURED" if report.live_openai else "NOT MEASURED"
    )
    return payload


def write_rag_reports(
    report: RagEvalReport,
    *,
    markdown_path: Path = DEFAULT_REPORT_MD,
    json_path: Path = DEFAULT_REPORT_JSON,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(render_rag_markdown(report), encoding="utf-8")
    json_path.write_text(
        json.dumps(report_to_json(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
