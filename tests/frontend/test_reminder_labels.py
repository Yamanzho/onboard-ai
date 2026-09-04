"""Phase 9G frontend reminder management copy."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RU = (ROOT / "frontend" / "src" / "i18n" / "ru.ts").read_text(encoding="utf-8")
DETAIL = (
    ROOT / "frontend" / "src" / "pages" / "assignments" / "AssignmentDetailPage.tsx"
).read_text(encoding="utf-8")
SETTINGS = (
    ROOT / "frontend" / "src" / "pages" / "CompanySettingsPage.tsx"
).read_text(encoding="utf-8")


def test_remind_now_and_history_on_assignment_detail() -> None:
    assert "remindNow" in DETAIL
    assert "remindNowDisabled" in DETAIL
    assert "remindersDisabled" in DETAIL
    assert "notificationsTitle" in DETAIL
    assert "labelReminderMode" in DETAIL
    assert "Напомнить сейчас" in RU
    assert "История уведомлений" in RU
    assert "Сотрудник отключил напоминания по этому назначению." in RU


def test_telegram_disable_label_unchanged() -> None:
    onboarding = (ROOT / "app" / "bot" / "keyboards" / "onboarding.py").read_text(
        encoding="utf-8"
    )
    assert "Не напоминать больше" in onboarding
    assert "disable automatic reminders" not in onboarding.lower()


def test_company_notification_window_fields() -> None:
    assert "windowStart" in SETTINGS
    assert "quietStart" in SETTINGS
    assert "notifications" in SETTINGS
    assert "Начало окна" in RU
