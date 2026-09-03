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
    ):
        assert needle.lower() in text.lower(), needle
