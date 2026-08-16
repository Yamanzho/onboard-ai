"""AI-8 RAG evaluation dataset shape. No secrets, no production PII."""

from __future__ import annotations

from app.services.ai.rag_eval import load_rag_eval_dataset

_FORBIDDEN = (
    "sk-",
    "BEGIN RSA",
    "password=",
    "api_key",
    "SECRET_KEY",
    "iban",
    "ssn",
)


def test_dataset_covers_required_categories() -> None:
    cases = load_rag_eval_dataset()
    assert 20 <= len(cases) <= 50
    labels = {label for case in cases for label in case.categories}
    assert {"answerable", "unanswerable", "ambiguous", "citation", "security"} <= labels
    by_label = {label: 0 for label in labels}
    for case in cases:
        for label in case.categories:
            by_label[label] += 1
    assert by_label["answerable"] >= 8
    assert by_label["unanswerable"] >= 6
    assert by_label["ambiguous"] >= 3
    assert by_label["citation"] >= 8
    assert by_label["security"] >= 2
    languages = {case.language for case in cases}
    assert languages == {"ru", "kk", "en"}


def test_dataset_has_no_secrets() -> None:
    cases = load_rag_eval_dataset()
    blob = "\n".join(case.question for case in cases).lower()
    for needle in _FORBIDDEN:
        assert needle.lower() not in blob


def test_unanswerable_have_no_gold_sources() -> None:
    cases = load_rag_eval_dataset()
    for case in cases:
        if not case.expected_answerable:
            assert case.expected_sources == ()
        if "citation" in case.categories:
            assert case.expected_sources
            assert case.expected_answerable
