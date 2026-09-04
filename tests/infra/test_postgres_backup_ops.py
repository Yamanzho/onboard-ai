from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.infra

ROOT = Path(__file__).resolve().parents[2]
SYSTEMD = ROOT / "deploy" / "systemd"
RUNBOOK = ROOT / "docs" / "runbooks" / "postgres-backup.md"
ENV_EXAMPLE = ROOT / ".env.example"


def test_backup_systemd_units_are_host_scheduled_and_persistent() -> None:
    backup_service = (
        SYSTEMD / "onboardai-postgres-backup.service"
    ).read_text(encoding="utf-8")
    backup_timer = (
        SYSTEMD / "onboardai-postgres-backup.timer"
    ).read_text(encoding="utf-8")
    verify_service = (
        SYSTEMD / "onboardai-postgres-restore-verify.service"
    ).read_text(encoding="utf-8")
    verify_timer = (
        SYSTEMD / "onboardai-postgres-restore-verify.timer"
    ).read_text(encoding="utf-8")

    assert "EnvironmentFile=/etc/onboard-ai/backup.env" in backup_service
    assert "scripts/postgres_backup.py" in backup_service
    assert "TimeoutStartSec=2h" in backup_service
    assert "OnCalendar=*-*-* 00,06,12,18:15:00 UTC" in backup_timer
    assert "Persistent=true" in backup_timer
    assert "scripts/postgres_restore_verify.py" in verify_service
    assert "--latest-remote --confirm-non-production" in verify_service
    assert "OnCalendar=*-*-* 03:30:00 UTC" in verify_timer
    assert "Persistent=true" in verify_timer
    combined = backup_service + verify_service
    assert "docker compose up" not in combined
    assert "api:" not in combined


def test_backup_environment_examples_are_placeholder_only() -> None:
    dedicated = (SYSTEMD / "backup.env.example").read_text(encoding="utf-8")
    application = ENV_EXAMPLE.read_text(encoding="utf-8")
    for needle in (
        "BACKUP_S3_ENDPOINT",
        "BACKUP_S3_BUCKET",
        "BACKUP_S3_PREFIX",
        "BACKUP_S3_ACCESS_KEY_ID",
        "BACKUP_S3_SECRET_ACCESS_KEY",
        "BACKUP_S3_SSE",
        "BACKUP_RETENTION_DAYS=30",
        "BACKUP_STATUS_FILE",
        "BACKUP_VERIFY_STATUS_FILE",
        "ONBOARDAI_BACKUP_ENFORCEMENT=0",
    ):
        assert needle in dedicated
        assert needle in application
    assert "AKIA" not in dedicated
    assert "s3-compatible.example.invalid" in dedicated


def test_runbook_defines_recovery_security_and_failure_contracts() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for needle in (
        "Target RPO",
        "6 hours",
        "Target RTO",
        "4 hours",
        "pg_dump",
        "onboard_owner",
        "BYPASSRLS",
        "onboard_app",
        "S3-compatible",
        "SHA-256",
        "AES256",
        "30-day",
        "systemctl enable --now",
        "--confirm-non-production",
        "Full VPS-loss recovery",
        "Credential compromise",
        "WAL archiving",
        "last-backup.json",
        "last-restore-verification.json",
        "DEFERRED — NOT A PILOT BLOCKER",
        "ONBOARDAI_BACKUP_ENFORCEMENT",
    ):
        assert needle in text
    assert "Do not start API/bot writers before database restoration" in text
