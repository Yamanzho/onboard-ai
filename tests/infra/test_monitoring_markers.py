from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.export_monitoring_markers import main, render_metrics

pytestmark = pytest.mark.infra


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_marker_export_includes_freshness_duration_size_and_result(tmp_path: Path) -> None:
    backup = tmp_path / "backup.json"
    restore = tmp_path / "restore.json"
    _write(
        backup,
        {
            "status": "success",
            "completed_at": "2026-09-03T18:15:00+00:00",
            "duration_seconds": 12.5,
            "bytes": 4096,
            "remote_uploaded": True,
            "retention_result": "success",
            "artifact": "must-not-be-exported.dump",
        },
    )
    _write(
        restore,
        {
            "status": "success",
            "completed_at": "2026-09-03T03:30:00+00:00",
            "duration_seconds": 30,
        },
    )
    output = render_metrics(backup, restore)
    assert "onboardai_backup_marker_valid 1" in output
    assert "onboardai_backup_remote_uploaded 1" in output
    assert "onboardai_backup_size_bytes 4096" in output
    assert "onboardai_restore_verification_success 1" in output
    assert "must-not-be-exported" not in output


def test_missing_or_failed_markers_fail_closed_without_leaking_content(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "backup.json"
    restore = tmp_path / "restore.json"
    _write(
        backup,
        {
            "status": "failed",
            "completed_at": "invalid",
            "secret": "do-not-export",
        },
    )
    output = render_metrics(backup, restore)
    assert "onboardai_backup_marker_valid 0" in output
    assert "onboardai_backup_last_success_timestamp_seconds 0.000" in output
    assert "onboardai_restore_verification_marker_valid 0" in output
    assert "do-not-export" not in output


def test_main_writes_atomic_prometheus_textfile(tmp_path: Path) -> None:
    output = tmp_path / "collector" / "onboardai.prom"
    assert main(
        [
            "--backup-marker",
            str(tmp_path / "missing-backup"),
            "--restore-marker",
            str(tmp_path / "missing-restore"),
            "--output",
            str(output),
        ]
    ) == 0
    assert output.exists()
    assert output.stat().st_mode & 0o777 == 0o644
    assert output.read_text().endswith("\n")
