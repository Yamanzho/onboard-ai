"""Phase 9D frontend product language (no DOM)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RU = (ROOT / "frontend" / "src" / "i18n" / "ru.ts").read_text(encoding="utf-8")
NAV = (ROOT / "frontend" / "src" / "lib" / "navigation.ts").read_text(encoding="utf-8")
ROUTES = (ROOT / "frontend" / "src" / "routes" / "AppRoutes.tsx").read_text(
    encoding="utf-8"
)


def test_management_course_labels() -> None:
    assert "onboarding: 'Курсы'" in RU
    assert "title: 'Курсы'" in RU
    assert "lockedExplanation:" in RU
    assert "revisionBadge:" in RU
    assert "contentBlocks:" in RU
    assert "myOnboarding: 'Мой онбординг'" in RU


def test_program_routes_unchanged() -> None:
    assert "/onboarding" in NAV
    assert 'path="onboarding"' in ROUTES
