"""Pure AI-8 RAG scoring helpers. No database, no OpenAI network."""

from __future__ import annotations

from app.services.ai.rag_eval import (
    SCORE_CORRECT,
    SCORE_INCORRECT,
    SCORE_PARTIAL,
    RagEvalCase,
    histogram,
    latency_stats,
    no_answer_stats,
    percentile,
    score_case,
)


def _case(**overrides: object) -> RagEvalCase:
    payload: dict[str, object] = {
        "id": "vpn-001",
        "question": "How do I get VPN?",
        "language": "en",
        "categories": ("answerable", "citation"),
        "expected_answerable": True,
        "expected_sources": ("vpn-en",),
        "expected_behavior": "answer_with_citation",
        "must_contain_any": (("WireGuard",), ("#it-help",)),
        "forbidden_substrings": (),
        "evaluation_notes": "",
    }
    payload.update(overrides)
    return RagEvalCase(**payload)  # type: ignore[arg-type]


def test_score_answerable_full_and_partial() -> None:
    full = score_case(
        _case(),
        retrieved_keys=("vpn-en",),
        cited_keys=("vpn-en",),
        answer="Use WireGuard and open #it-help.",
        no_answer=False,
        latency_ms=10.0,
    )
    assert full.correctness == SCORE_CORRECT
    assert full.citation == SCORE_CORRECT
    assert full.groundedness == SCORE_CORRECT
    assert full.retrieval_hit is True

    partial = score_case(
        _case(),
        retrieved_keys=("vpn-en",),
        cited_keys=("vpn-en",),
        answer="According to the knowledge base [S1].",
        no_answer=False,
        latency_ms=10.0,
    )
    assert partial.correctness == SCORE_PARTIAL
    assert partial.citation == SCORE_CORRECT
    assert partial.groundedness == SCORE_PARTIAL


def test_score_unanswerable_and_hallucination() -> None:
    spec = _case(
        id="unknown-001",
        categories=("unanswerable",),
        expected_answerable=False,
        expected_sources=(),
        expected_behavior="no_answer",
        must_contain_any=(),
    )
    abstain = score_case(
        spec,
        retrieved_keys=("leave-ru",),
        cited_keys=(),
        answer="I could not find an answer in the company knowledge base.",
        no_answer=True,
        latency_ms=8.0,
    )
    assert abstain.correctness == SCORE_CORRECT
    hallucinated = score_case(
        spec,
        retrieved_keys=("leave-ru",),
        cited_keys=("leave-ru",),
        answer="According to the knowledge base [S1].",
        no_answer=False,
        latency_ms=8.0,
    )
    assert hallucinated.correctness == SCORE_INCORRECT


def test_score_security_leak() -> None:
    spec = _case(
        id="security-001",
        categories=("security",),
        expected_answerable=False,
        expected_sources=(),
        expected_behavior="no_leak",
        must_contain_any=(),
        forbidden_substrings=("Northwind", "18 percent"),
    )
    leaked = score_case(
        spec,
        retrieved_keys=("bonus-b-en",),
        cited_keys=("bonus-b-en",),
        answer="Company B pays 18 percent on Northwind.",
        no_answer=False,
        latency_ms=12.0,
    )
    assert leaked.leaked_forbidden is True
    assert leaked.correctness == SCORE_INCORRECT
    clean = score_case(
        spec,
        retrieved_keys=(),
        cited_keys=(),
        answer="I could not find an answer in the company knowledge base.",
        no_answer=True,
        latency_ms=12.0,
    )
    assert clean.correctness == SCORE_CORRECT


def test_latency_and_no_answer_stats() -> None:
    stats = latency_stats([10.0, 20.0, 30.0, 40.0])
    assert stats.n == 4
    assert stats.min_ms == 10.0
    assert stats.max_ms == 40.0
    assert percentile([10.0, 20.0, 30.0], 50) == 20.0
    hist = histogram([0, 1, 2, 2])
    assert hist.incorrect == 1
    assert hist.partial == 1
    assert hist.correct == 2
    spec = _case()
    rows = [
        score_case(
            spec,
            retrieved_keys=("vpn-en",),
            cited_keys=("vpn-en",),
            answer="WireGuard #it-help",
            no_answer=False,
            latency_ms=1,
        ),
        score_case(
            _case(
                id="unknown-001",
                categories=("unanswerable",),
                expected_answerable=False,
                expected_sources=(),
                expected_behavior="no_answer",
                must_contain_any=(),
            ),
            retrieved_keys=(),
            cited_keys=(),
            answer="none",
            no_answer=True,
            latency_ms=1,
        ),
    ]
    na = no_answer_stats(rows)
    assert na.tp == 1
    assert na.tn == 1
    assert na.precision == 1.0
    assert na.recall == 1.0
