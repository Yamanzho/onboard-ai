from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.postgres_backup import BackupConfig, perform_backup
from scripts.postgres_restore_verify import verify_backup

pytestmark = [
    pytest.mark.infra,
    pytest.mark.backup_restore,
    pytest.mark.skipif(
        os.environ.get("ONBOARDAI_BACKUP_RESTORE_SMOKE") != "1",
        reason="set ONBOARDAI_BACKUP_RESTORE_SMOKE=1 for destructive disposable smoke",
    ),
    pytest.mark.skipif(shutil.which("docker") is None, reason="Docker is required"),
]

ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"{result.stderr}"
        )


def _run_with_retry(
    command: list[str],
    *,
    env: dict[str, str],
    attempts: int = 20,
) -> None:
    last_error: AssertionError | None = None
    for _attempt in range(attempts):
        try:
            _run(command, env=env)
            return
        except AssertionError as exc:
            last_error = exc
            time.sleep(0.5)
    assert last_error is not None
    raise last_error


def _wait_for_source(container: str, port: int) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        result = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "pg_isready",
                "--username=onboard",
                "--dbname=onboard_ai_backup_source",
            ],
            check=False,
            capture_output=True,
        )
        if result.returncode == 0:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return
            except OSError:
                pass
        time.sleep(0.5)
    raise AssertionError("source PostgreSQL did not become ready")


def test_full_dump_destroy_restore_preserves_data_schema_rls_and_roles(
    tmp_path: Path,
) -> None:
    suffix = uuid4().hex[:10]
    source = f"onboardai-backup-source-{suffix}"
    verify_container = f"onboardai-restore-verify-{suffix}"
    port = _free_port()
    postgres_password = "backup-smoke-bootstrap-password"
    owner_password = "backup-smoke-owner-password"
    app_password = "backup-smoke-app-password"
    database = "onboard_ai_backup_source"
    company_id = uuid4()
    source_running = False
    try:
        docker_env = dict(os.environ)
        docker_env["POSTGRES_PASSWORD"] = postgres_password
        _run(
            [
                "docker",
                "run",
                "--rm",
                "--detach",
                "--name",
                source,
                "-e",
                "POSTGRES_USER=onboard",
                "-e",
                "POSTGRES_PASSWORD",
                "-e",
                f"POSTGRES_DB={database}",
                "-p",
                f"127.0.0.1:{port}:5432",
                "pgvector/pgvector:pg16",
            ],
            env=docker_env,
        )
        source_running = True
        _wait_for_source(source, port)

        env = {
            **os.environ,
            "APP_ENV": "development",
            "SECRET_KEY": "backup-smoke-secret-key-at-least-32-characters",
            "SUPER_ADMIN_PASSWORD": "backup-smoke-super-admin-password",
            "BOT_SERVICE_TOKEN": "backup-smoke-bot-service-token-32chars",
            "POSTGRES_USER": "onboard",
            "POSTGRES_PASSWORD": postgres_password,
            "POSTGRES_DB": database,
            "POSTGRES_HOST": "127.0.0.1",
            "POSTGRES_PORT": str(port),
            "ONBOARD_OWNER_PASSWORD": owner_password,
            "ONBOARD_APP_PASSWORD": app_password,
            "DATABASE_URL": (
                f"postgresql+asyncpg://onboard_app:{app_password}"
                f"@127.0.0.1:{port}/{database}"
            ),
            "MIGRATION_DATABASE_URL": (
                f"postgresql+asyncpg://onboard_owner:{owner_password}"
                f"@127.0.0.1:{port}/{database}"
            ),
            "BOOTSTRAP_DATABASE_URL": (
                f"postgresql://onboard:{postgres_password}"
                f"@127.0.0.1:{port}/{database}"
            ),
        }
        _run_with_retry(
            [sys.executable, "-m", "scripts.bootstrap_rls_roles"],
            env=env,
        )
        _run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        insert_sql = (
            "INSERT INTO companies "
            "(id, name, slug, timezone, is_active, settings) VALUES "
            f"('{company_id}', 'Backup Smoke Company', "
            f"'backup-smoke-{suffix}', 'UTC', true, '{{}}'::jsonb);"
        )
        _run(
            [
                "docker",
                "exec",
                source,
                "psql",
                "--username=onboard",
                f"--dbname={database}",
                "--set=ON_ERROR_STOP=1",
                "--command",
                insert_sql,
            ]
        )

        backup = perform_backup(
            BackupConfig(
                compose_dir=ROOT,
                backup_dir=tmp_path / "backups",
                status_file=tmp_path / "last-backup.json",
                database=database,
                owner_password=owner_password,
                source_container=source,
                bucket=None,
                prefix="onboardai/postgres/",
                endpoint=None,
                region="us-east-1",
                access_key_id=None,
                secret_access_key=None,
                sse="AES256",
                kms_key_id=None,
                retention_days=30,
                local_only=True,
            ),
            timestamp="20260904T010203Z",
        )
        checksum = backup.with_name(f"{backup.name}.sha256")
        subprocess.run(
            ["docker", "rm", "--force", source],
            check=True,
            capture_output=True,
        )
        source_running = False

        marker = verify_backup(
            backup,
            checksum,
            container_name=verify_container,
            status_file=tmp_path / "last-restore-verification.json",
        )
        verification = marker["verification"]
        assert isinstance(verification, dict)
        assert verification["companies"] == 1
        assert verification["alembic_revision"]
        assert marker["bytes"] == backup.stat().st_size
    finally:
        if source_running:
            subprocess.run(
                ["docker", "rm", "--force", source],
                check=False,
                capture_output=True,
            )
        subprocess.run(
            ["docker", "rm", "--force", verify_container],
            check=False,
            capture_output=True,
        )
