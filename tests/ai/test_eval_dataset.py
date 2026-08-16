"""AI-7 dataset shape: 30–50 synthetic cases, RU/KK/EN, no secrets."""

from __future__ import annotations

from app.services.ai.eval_corpus import (
    EVAL_ARTICLES,
    EVAL_CASES,
    answerable_cases,
    articles_by_key,
    no_answer_cases,
)

_FORBIDDEN = (
    "sk-",
    "BEGIN RSA",
    "password=",
    "api_key",
    "SECRET_KEY",
    "telegram",
    "iban",
    "ssn",
)


def test_dataset_size_and_languages() -> None:
    assert 30 <= len(EVAL_CASES) <= 50
    languages = {case.language for case in EVAL_CASES}
    assert languages == {"ru", "kk", "en"}
    counts = {lang: 0 for lang in languages}
    for case in EVAL_CASES:
        counts[case.language] += 1
    assert all(count >= 5 for count in counts.values())


def test_no_answer_and_cross_language_present() -> None:
    absent = no_answer_cases()
    assert 5 <= len(absent) <= 12
    assert all(case.expect_no_answer and not case.expected_keys for case in absent)
    cross = [case for case in answerable_cases() if case.cross_language]
    assert len(cross) >= 6
    assert any(case.language == "ru" and "en" in case.id for case in cross)
    assert any(case.id.startswith("cross-en-ru") for case in cross)
    assert any(case.id.startswith("cross-kk-ru") for case in cross)
    assert any(case.id.startswith("cross-ru-kk") for case in cross)
    assert any(case.id.startswith("cross-kk-en") for case in cross)
    for case in cross:
        assert case.target_language in {"ru", "kk", "en"}
        assert case.target_language != case.language
    pairs = {(case.language, case.target_language) for case in cross}
    assert pairs >= {
        ("ru", "en"),
        ("en", "ru"),
        ("kk", "ru"),
        ("ru", "kk"),
        ("en", "kk"),
        ("kk", "en"),
    }


def test_expected_keys_exist_and_company_b_is_present() -> None:
    keys = articles_by_key()
    assert "bonus-b-en" in keys
    assert keys["bonus-b-en"].company == "b"
    assert any(article.company == "a" for article in EVAL_ARTICLES)
    for case in answerable_cases():
        assert case.expected_keys
        for key in case.expected_keys:
            assert key in keys
            assert keys[key].company == "a"


def test_dataset_has_no_secrets_or_employee_pii() -> None:
    blob = "\n".join(
        [
            *(f"{article.title}\n{article.body}" for article in EVAL_ARTICLES),
            *(case.question for case in EVAL_CASES),
        ]
    ).lower()
    for needle in _FORBIDDEN:
        assert needle.lower() not in blob
    assert "@gmail.com" not in blob
    assert "onboard.example" in blob


def test_chunking_fixture_coverage() -> None:
    kinds = {article.chunking for article in EVAL_ARTICLES if article.chunking}
    assert {"short", "medium", "long", "table"} <= kinds
    langs = {article.language for article in EVAL_ARTICLES}
    assert langs >= {"ru", "kk", "en"}
