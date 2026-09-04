"""Phase 9H frontend acknowledgement copy and selectors."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RU = (ROOT / "frontend" / "src" / "i18n" / "ru.ts").read_text(encoding="utf-8")
CREATE = (
    ROOT / "frontend" / "src" / "pages" / "assignments" / "AssignmentCreatePage.tsx"
).read_text(encoding="utf-8")
DETAIL = (
    ROOT / "frontend" / "src" / "pages" / "assignments" / "AssignmentDetailPage.tsx"
).read_text(encoding="utf-8")
PANEL = (
    ROOT / "frontend" / "src" / "pages" / "employee" / "AcknowledgementPanel.tsx"
).read_text(encoding="utf-8")
TYPES = (ROOT / "frontend" / "src" / "types" / "assignment.ts").read_text(encoding="utf-8")


def test_assignment_type_selector_and_document_picker() -> None:
    assert "ASSIGNMENT_TYPES" in CREATE
    assert "assignmentType" in CREATE
    assert "AcknowledgementDocumentPicker" in CREATE
    assert "labelAssignmentType" in CREATE
    assert "assignment_type?: AssignmentType" in TYPES or "assignment_type?:" in TYPES
    assert "'acknowledgement'" in TYPES


def test_exact_version_and_status_labels() -> None:
    assert "colVersion" in DETAIL
    assert "acknowledgedYes" in DETAIL
    assert "acknowledgedNo" in DETAIL
    assert "acknowledged_at" in DETAIL
    assert "item.version" in DETAIL
    assert "acknowledgeAction" in PANEL
    assert "versionLabel" in PANEL


def test_no_electronic_signature_wording() -> None:
    forbidden = (
        "Электронная подпись",
        "электронная подпись",
        "Подписать",
        "Юридически подтверждаю",
        "e-signature",
        "electronic signature",
    )
    for blob in (RU, CREATE, DETAIL, PANEL):
        lower = blob.lower()
        for phrase in forbidden:
            assert phrase.lower() not in lower
    assert "Я ознакомился" in RU
    assert "Ознакомлен" in RU
    assert "Ознакомление" in RU
