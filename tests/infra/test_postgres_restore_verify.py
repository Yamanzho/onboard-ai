from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts.postgres_restore_verify import (
    RestoreVerificationError,
    _integrity_sql,
    _safe_container_name,
    _validate_artifact,
    main,
    verify_backup,
)

pytestmark = pytest.mark.infra


def _artifact(tmp_path: Path) -> tuple[Path, Path]:
    artifact = (
        tmp_path / "onboardai-postgres-onboard_ai-20260904T010203Z.dump"
    )
    artifact.write_bytes(b"PGDMPrestore-verification-payload")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    checksum = artifact.with_name(f"{artifact.name}.sha256")
    checksum.write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
    return artifact, checksum


def _completed(
    command: list[str],
    *,
    returncode: int = 0,
    stdout: str | bytes = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")


def test_restore_refuses_without_confirmation(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact, checksum = _artifact(tmp_path)
    result = main(["--artifact", str(artifact), "--checksum", str(checksum)])
    assert result == 2
    assert "--confirm-non-production" in capsys.readouterr().err


@pytest.mark.parametrize(
    "name",
    ["db", "onboard-ai-db", "onboard-ai_postgres_data", "onboard_ai"],
)
def test_restore_refuses_production_looking_targets(name: str) -> None:
    with pytest.raises(RestoreVerificationError, match="disposable restore prefix"):
        _safe_container_name(name)


def test_restore_requires_recognized_disposable_container_prefix() -> None:
    accepted = _safe_container_name("onboardai-restore-verify-unit")
    assert accepted == "onboardai-restore-verify-unit"
    generated = _safe_container_name(None)
    assert generated.startswith("onboardai-restore-verify-")


def test_artifact_validation_rejects_checksum_mismatch(tmp_path: Path) -> None:
    artifact, checksum = _artifact(tmp_path)
    checksum.write_text(f"{'0' * 64}  {artifact.name}\n", encoding="ascii")
    with pytest.raises(RestoreVerificationError, match="checksum mismatch"):
        _validate_artifact(artifact, checksum)


def test_artifact_validation_rejects_wrong_format(tmp_path: Path) -> None:
    artifact, checksum = _artifact(tmp_path)
    artifact.write_bytes(b"not-a-postgres-dump")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    checksum.write_text(f"{digest}  {artifact.name}\n", encoding="ascii")
    with pytest.raises(RestoreVerificationError, match="custom format"):
        _validate_artifact(artifact, checksum)


def test_isolated_restore_runs_catalog_restore_integrity_and_cleanup(
    tmp_path: Path,
) -> None:
    artifact, checksum = _artifact(tmp_path)
    status_file = tmp_path / "status" / "verify.json"
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        command = list(command)
        commands.append(command)
        if "pg_isready" in command:
            return _completed(command)
        if "psql" in command and "integrity_checks" not in command:
            sql = command[-1] if command[-2] == "--command" else ""
            if "json_build_object" in sql:
                return _completed(
                    command,
                    stdout=json.dumps(
                        {
                            "alembic_revision": "e3f4a5b6c7d8",
                            "companies": 1,
                            "employees": 1,
                            "policies": 20,
                        }
                    ),
                )
        return _completed(command)

    marker = verify_backup(
        artifact,
        checksum,
        container_name="onboardai-restore-verify-unit",
        status_file=status_file,
        run_command=fake_run,
    )

    rendered = [" ".join(command) for command in commands]
    assert any("pg_restore --list /tmp/backup.dump" in line for line in rendered)
    assert any(
        "pg_restore --username=postgres --dbname=onboardai_restore_verify "
        "--exit-on-error /tmp/backup.dump" in line
        for line in rendered
    )
    assert any("docker rm --force onboardai-restore-verify-unit" in line for line in rendered)
    assert all("onboard-ai-db" not in line for line in rendered)
    assert marker["status"] == "success"
    assert json.loads(status_file.read_text())["verification"]["companies"] == 1


def test_restore_cleanup_runs_when_restore_fails(tmp_path: Path) -> None:
    artifact, checksum = _artifact(tmp_path)
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        command = list(command)
        commands.append(command)
        if "pg_isready" in command:
            return _completed(command)
        if "pg_restore" in command and "--exit-on-error" in command:
            return _completed(command, returncode=1)
        return _completed(command)

    with pytest.raises(RestoreVerificationError, match="restore failed"):
        verify_backup(
            artifact,
            checksum,
            container_name="onboardai-restore-verify-failure",
            run_command=fake_run,
        )
    assert ["docker", "rm", "--force", "onboardai-restore-verify-failure"] in commands


def test_integrity_sql_covers_schema_rls_roles_and_constraints() -> None:
    sql = _integrity_sql()
    for needle in (
        "pg_extension",
        "vector",
        "alembic_version",
        "idempotency_receipts",
        "telegram_outbound_messages",
        "relforcerowsecurity",
        "pg_policies",
        "app.company_id()",
        "app.employee_id()",
        "rolbypassrls",
        "has_table_privilege",
        "pg_constraint",
        "assignments",
        "progress",
    ):
        assert needle in sql
