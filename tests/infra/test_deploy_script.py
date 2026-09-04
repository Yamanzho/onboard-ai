from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.infra
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "deploy_production.sh"
RUNBOOK = ROOT / "docs" / "runbooks" / "safe-deployment.md"


def test_deploy_script_is_non_destructive_and_sequences_migrate_first() -> None:
    assert SCRIPT.is_file()
    text = SCRIPT.read_text(encoding="utf-8")
    assert "docker compose" in text
    assert "run --rm migrate" in text
    assert "force-recreate api" in text
    assert "/ready" in text
    assert "/health" in text
    assert "down -v" not in text
    assert "volume rm" not in text
    assert "push" not in text
    assert "does not roll back automatically" in text


def test_deploy_script_includes_local_override_and_fail_closes_volume() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "docker-compose.prod.local.yml" in text
    assert "if [ -f docker-compose.prod.local.yml ]" in text
    assert "preflight: compose files:" in text
    assert "preflight: postgres volume" in text
    assert "ONBOARDAI_REQUIRED_POSTGRES_VOLUME" in text
    assert "postgres_data must be an external volume" in text
    assert "does not match live" in text
    assert "refusing to create a replacement" in text
    assert "onboard-ai_postgres_data_pgvector" not in text
    assert "COMPOSE_FILES=" in text


def test_deploy_script_does_not_require_remote_backup() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "not a deploy blocker" in text
    assert "accepted pilot risk" in text.lower()
    assert "continue only if a recent backup is confirmed" not in text
    assert "aws" not in text.lower()
    assert "backup.env" not in text
    assert "BACKUP_S3_" not in text
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("_die") and "backup" in stripped.lower():
            raise AssertionError(f"deploy script fail-closes on backup: {stripped}")


def test_deploy_script_shell_syntax() -> None:
    shell = shutil.which("sh") or shutil.which("bash")
    if shell is None:
        pytest.skip("no shell")
    subprocess.run([shell, "-n", str(SCRIPT)], check=True)


def test_safe_deployment_runbook_is_honest_about_single_instance() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for needle in (
        "starting",
        "ready",
        "draining",
        "stopped",
        "single",
        "zero-downtime",
        "migrate",
        "backward compatible",
        "do not delete",
        "45",
        "Telegram outbound",
        "KB indexing",
        "deferred",
        "accepted pilot risk",
    ):
        assert needle.lower() in text.lower(), needle
    assert "Confirm a recent successful backup marker" not in text
