"""Production backup + golden-path runbooks must exist and stay operator-only."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "docs" / "runbooks" / "postgres-backup.md"
GOLDEN = ROOT / "docs" / "runbooks" / "production-pilot-golden-path.md"
DEPLOYMENT = ROOT / "DEPLOYMENT.md"


def test_postgres_backup_runbook_covers_pilot_ops() -> None:
    assert BACKUP.is_file()
    text = BACKUP.read_text(encoding="utf-8")
    assert "pg_dump" in text
    assert "off the VPS" in text or "off-box" in text
    assert "age" in text.lower() or "gpg" in text.lower() or "encrypt" in text.lower()
    assert "retention" in text.lower()
    assert "pg_restore" in text
    assert "verification" in text.lower() or "drill" in text.lower()
    assert "Do not add backup workers" in text or "does not ship backup" in text.lower()


def test_golden_path_runbook_covers_pilot_flow() -> None:
    assert GOLDEN.is_file()
    text = GOLDEN.read_text(encoding="utf-8")
    for needle in (
        "Super Admin",
        "Create company",
        "Create HR",
        "Create Employee",
        "invite",
        "Telegram",
        "/start",
        "Publish",
        "Assign",
        "progress",
        "SEED_DEMO",
        "BOT_COMPANY_ID",
        "/invite#",
    ):
        assert needle in text, f"missing {needle!r}"


def test_deployment_links_backup_and_golden_path() -> None:
    text = DEPLOYMENT.read_text(encoding="utf-8")
    assert "postgres-backup.md" in text
    assert "production-pilot-golden-path.md" in text
    assert "SEED_DEMO=false" in text
    assert "/ready" in text
    assert "/health" in text
