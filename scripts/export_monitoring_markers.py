"""Export Phase 8A status markers for node_exporter's textfile collector."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_BACKUP_MARKER = Path(
    os.environ.get(
        "BACKUP_STATUS_FILE",
        "/var/lib/onboard-ai-backup/last-backup.json",
    )
)
DEFAULT_RESTORE_MARKER = Path(
    os.environ.get(
        "BACKUP_VERIFY_STATUS_FILE",
        "/var/lib/onboard-ai-backup/last-restore-verification.json",
    )
)
DEFAULT_OUTPUT = Path(
    os.environ.get(
        "MONITORING_TEXTFILE_OUTPUT",
        "/var/lib/node_exporter/textfile_collector/onboardai_backup.prom",
    )
)


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(0.0, float(value))


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value.strip():
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, parsed.timestamp())


def _read_marker(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def render_metrics(backup_path: Path, restore_path: Path) -> str:
    """Render only fixed metric names and numeric values; marker strings stay private."""
    backup = _read_marker(backup_path)
    restore = _read_marker(restore_path)
    backup_timestamp = _timestamp(backup.get("completed_at"))
    restore_timestamp = _timestamp(restore.get("completed_at"))
    backup_valid = backup.get("status") == "success" and backup_timestamp > 0
    restore_valid = restore.get("status") == "success" and restore_timestamp > 0
    lines = [
        "# HELP onboardai_backup_marker_valid Latest backup marker is valid.",
        "# TYPE onboardai_backup_marker_valid gauge",
        f"onboardai_backup_marker_valid {int(backup_valid)}",
        "# HELP onboardai_backup_last_success_timestamp_seconds Backup completion time.",
        "# TYPE onboardai_backup_last_success_timestamp_seconds gauge",
        f"onboardai_backup_last_success_timestamp_seconds {backup_timestamp:.3f}",
        "# HELP onboardai_backup_duration_seconds Latest backup duration.",
        "# TYPE onboardai_backup_duration_seconds gauge",
        f"onboardai_backup_duration_seconds {_number(backup.get('duration_seconds')):.3f}",
        "# HELP onboardai_backup_size_bytes Latest backup artifact size.",
        "# TYPE onboardai_backup_size_bytes gauge",
        f"onboardai_backup_size_bytes {_number(backup.get('bytes')):.0f}",
        "# HELP onboardai_backup_remote_uploaded Latest backup was uploaded off-host.",
        "# TYPE onboardai_backup_remote_uploaded gauge",
        f"onboardai_backup_remote_uploaded {int(backup.get('remote_uploaded') is True)}",
        "# HELP onboardai_backup_retention_warning Latest backup retention had a warning.",
        "# TYPE onboardai_backup_retention_warning gauge",
        (
            "onboardai_backup_retention_warning "
            f"{int(backup.get('retention_result') == 'warning')}"
        ),
        (
            "# HELP onboardai_restore_verification_marker_valid "
            "Latest restore marker is valid."
        ),
        "# TYPE onboardai_restore_verification_marker_valid gauge",
        f"onboardai_restore_verification_marker_valid {int(restore_valid)}",
        (
            "# HELP onboardai_restore_verification_last_success_timestamp_seconds "
            "Restore verification completion time."
        ),
        "# TYPE onboardai_restore_verification_last_success_timestamp_seconds gauge",
        (
            "onboardai_restore_verification_last_success_timestamp_seconds "
            f"{restore_timestamp:.3f}"
        ),
        "# HELP onboardai_restore_verification_duration_seconds Latest verification duration.",
        "# TYPE onboardai_restore_verification_duration_seconds gauge",
        (
            "onboardai_restore_verification_duration_seconds "
            f"{_number(restore.get('duration_seconds')):.3f}"
        ),
        "# HELP onboardai_restore_verification_success Latest verification succeeded.",
        "# TYPE onboardai_restore_verification_success gauge",
        f"onboardai_restore_verification_success {int(restore_valid)}",
    ]
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o644)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-marker", type=Path, default=DEFAULT_BACKUP_MARKER)
    parser.add_argument("--restore-marker", type=Path, default=DEFAULT_RESTORE_MARKER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    write_atomic(
        args.output,
        render_metrics(args.backup_marker, args.restore_marker),
    )
    print("onboardai_monitoring_markers event=export_success", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
