"""Phase 9E frontend: structured quiz editor and employee-safe types."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STEP_FORM = (
    ROOT / "frontend" / "src" / "components" / "onboarding" / "StepForm.tsx"
).read_text(encoding="utf-8")
UTILS = (
    ROOT / "frontend" / "src" / "components" / "onboarding" / "stepFormUtils.ts"
).read_text(encoding="utf-8")
QUIZ_TYPES = (ROOT / "frontend" / "src" / "types" / "quiz.ts").read_text(encoding="utf-8")
QUIZ_UTILS = (ROOT / "frontend" / "src" / "lib" / "quizUtils.ts").read_text(
    encoding="utf-8"
)
RU = (ROOT / "frontend" / "src" / "i18n" / "ru.ts").read_text(encoding="utf-8")
DETAIL = (
    ROOT / "frontend" / "src" / "pages" / "assignments" / "AssignmentDetailPage.tsx"
).read_text(encoding="utf-8")
ONBOARDING = (
    ROOT / "frontend" / "src" / "pages" / "employee" / "MyOnboardingPage.tsx"
).read_text(encoding="utf-8")


def test_new_quiz_editor_is_structured_not_freetext() -> None:
    assert "single_choice" in STEP_FORM
    assert "multiple_choice" in STEP_FORM
    assert "correct_option_ids" in STEP_FORM
    assert "Вопрос | правильный ответ" not in RU
    assert "questionsFromText" not in STEP_FORM
    assert "serializeStructuredQuiz" in UTILS
    assert "newStructuredQuestion" in UTILS


def test_legacy_quiz_is_not_silently_overwritten() -> None:
    assert "legacyQuizNotice" in STEP_FORM
    assert "quiz_convert" in UTILS
    assert "quiz_is_legacy" in UTILS


def test_score_summary_renders() -> None:
    assert "quizBestScore" in DETAIL
    assert "quizAttempts" in DETAIL
    assert "parseQuizAttemptSummary" in DETAIL
    assert "parseQuizAttemptSummary" in ONBOARDING
    assert "JSON.stringify(item.payload" not in DETAIL


def test_employee_quiz_type_has_no_answer_key() -> None:
    employee_block = QUIZ_TYPES.split("export interface EmployeeQuizQuestion")[1].split(
        "export interface"
    )[0]
    assert "correct_option_ids" not in employee_block
    parser = QUIZ_UTILS.split("parseEmployeeQuizQuestions")[1].split(
        "export function parseQuizAttemptSummary"
    )[0]
    assert "correct_option_ids" not in parser
