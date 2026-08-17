"""Validate the WoW KB test corpus fixtures without touching production data."""

from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "wow"
CORPUS_PATH = FIXTURES / "corpus.json"
QUIZ_PATH = FIXTURES / "quiz.json"
EVAL_PATH = FIXTURES / "rag_eval.json"

FORBIDDEN_PHRASES = (
    "зарплата",
    "номер телефона",
    "золота зарабатывал",
    "текущая цена",
    "следующем патче",
    "следующий рейд",
    "pvp рейтинг",
    "игровой аккаунт",
    "зарток",
    "небесный картель",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _main_body(markdown: str) -> str:
    marker = "\n## См. также"
    if marker in markdown:
        return markdown.split(marker, 1)[0]
    return markdown


def test_corpus_has_eight_russian_articles() -> None:
    corpus = _load(CORPUS_PATH)
    assert corpus["corpus_id"] == "wow-test-corpus-v1"
    assert corpus["language"] == "ru"
    assert corpus["tenant_slug"] == "demo"
    articles = corpus["articles"]
    assert len(articles) == 8
    ids = [item["id"] for item in articles]
    assert ids == [
        "azeroth",
        "alliance-horde",
        "arthas",
        "nerzhul",
        "orcs-draenor",
        "illidan",
        "jaina",
        "sylvanas",
    ]
    for item in articles:
        assert 700 <= item["word_count"] <= 1500
        assert item["title"]
        assert item["body"].startswith("# ")
        assert "## Введение" in item["body"]
        assert "## Краткий итог" in item["body"]
        assert item["body_format"] == "markdown"
        assert item["identity_tag"] == f"wow-{item['id']}"


def test_unique_markers_belong_to_one_article() -> None:
    articles = _load(CORPUS_PATH)["articles"]
    for article in articles:
        for marker in article["unique_markers"]:
            owners = [
                other["id"]
                for other in articles
                if marker in _main_body(other["body"])
            ]
            assert owners == [article["id"]], marker


def test_corpus_omits_no_answer_topics() -> None:
    blob = "\n".join(item["body"] for item in _load(CORPUS_PATH)["articles"]).lower()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in blob, phrase


def test_quiz_has_required_mix() -> None:
    quiz = _load(QUIZ_PATH)
    questions = quiz["questions"]
    assert quiz["quiz_id"] == "wow-test-quiz-v1"
    assert len(questions) == 20
    by_diff = {"easy": 0, "medium": 0, "hard": 0}
    article_ids = {item["id"] for item in _load(CORPUS_PATH)["articles"]}
    for question in questions:
        by_diff[question["difficulty"]] += 1
        assert question["type"] in {"single_choice", "multiple_choice", "true_false"}
        assert question["options"]
        assert question["correct_indices"]
        assert set(question["source_articles"]) <= article_ids
        for index in question["correct_indices"]:
            assert 0 <= index < len(question["options"])
    assert by_diff == {"easy": 10, "medium": 6, "hard": 4}


def test_rag_eval_case_counts() -> None:
    payload = _load(EVAL_PATH)
    cases = payload["cases"]
    assert len(cases) == 30
    by_behavior = {"answer": 0, "ambiguous": 0, "no_answer": 0}
    article_ids = {item["id"] for item in _load(CORPUS_PATH)["articles"]}
    for case in cases:
        by_behavior[case["expected_behavior"]] += 1
        assert case["id"]
        assert case["question"]
        if case["expected_behavior"] == "no_answer":
            assert case["expected_articles"] == []
        else:
            assert case["expected_articles"]
            assert set(case["expected_articles"]) <= article_ids
        if case["expected_behavior"] == "ambiguous":
            assert len(case["expected_articles"]) >= 2
    assert by_behavior == {"answer": 12, "ambiguous": 8, "no_answer": 10}
    assert payload["summary"] == {
        "answerable": 12,
        "ambiguous": 8,
        "unanswerable": 10,
        "total": 30,
    }
