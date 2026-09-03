from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import scripts.postgres_backup as backup_module
from scripts.postgres_backup import (
    BackupConfig,
    BackupError,
    _dump_command,
    _recognized_remote_key,
    perform_backup,
)

pytestmark = pytest.mark.infra


def _config(tmp_path: Path, *, local_only: bool = True) -> BackupConfig:
    return BackupConfig(
        compose_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        status_file=tmp_path / "status" / "last-backup.json",
        database="onboard_ai",
        owner_password="unit-owner-password",
        source_container="onboardai-unit-source",
        bucket=None if local_only else "private-test-bucket",
        prefix="onboardai/postgres/",
        endpoint=None if local_only else "https://objects.example.test",
        region="us-east-1",
        access_key_id=None if local_only else "unit-access-key",
        secret_access_key=None if local_only else "unit-secret-key",
        sse="AES256",
        kms_key_id=None,
        retention_days=30,
        local_only=local_only,
    )


def _completed(
    command: list[str],
    *,
    returncode: int = 0,
    stdout: str | bytes = "",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr="")


def test_backup_config_requires_remote_credentials_and_https(tmp_path: Path) -> None:
    base = {
        "ONBOARD_OWNER_PASSWORD": "owner-password",
        "BACKUP_LOCAL_DIR": str(tmp_path),
    }
    with pytest.raises(BackupError, match="remote backup requires"):
        BackupConfig.from_env(local_only=False, environ=base)
    with pytest.raises(BackupError, match="must use HTTPS"):
        BackupConfig.from_env(
            local_only=False,
            environ={
                **base,
                "BACKUP_S3_BUCKET": "bucket",
                "BACKUP_S3_ACCESS_KEY_ID": "key",
                "BACKUP_S3_SECRET_ACCESS_KEY": "secret",
                "BACKUP_S3_ENDPOINT": "http://insecure.example.test",
            },
        )


def test_dump_command_uses_owner_custom_format_without_password_argument(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    command = _dump_command(config)
    rendered = " ".join(command)
    assert "pg_dump" in command
    assert "--username=onboard_owner" in command
    assert "--format=custom" in command
    assert "--compress=9" in command
    assert "unit-owner-password" not in rendered
    assert "onboard_app" not in rendered


def test_local_backup_is_atomic_checksummed_and_secret_free(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = _config(tmp_path)

    def fake_run(command, **kwargs):
        assert "unit-owner-password" not in " ".join(command)
        kwargs["stdout"].write(b"PGDMPunit-test-payload")
        return _completed(command)

    artifact = perform_backup(
        config,
        timestamp="20260904T010203Z",
        now=datetime(2026, 9, 4, 1, 2, 3, tzinfo=UTC),
        run_command=fake_run,
    )

    assert artifact.name == "onboardai-postgres-onboard_ai-20260904T010203Z.dump"
    assert artifact.read_bytes().startswith(b"PGDMP")
    assert artifact.stat().st_mode & 0o777 == 0o600
    sidecar = artifact.with_name(f"{artifact.name}.sha256")
    assert sidecar.is_file()
    assert sidecar.read_text().endswith(f"  {artifact.name}\n")
    marker = json.loads(config.status_file.read_text())
    assert marker["status"] == "success"
    assert marker["remote_uploaded"] is False
    assert not list(config.backup_dir.glob("*.partial"))
    assert "unit-owner-password" not in capsys.readouterr().out


def test_failed_dump_returns_error_and_removes_incomplete_files(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)

    def fake_run(command, **kwargs):
        kwargs["stdout"].write(b"PGDMPpartial")
        return _completed(command, returncode=2)

    with pytest.raises(BackupError, match="pg_dump failed"):
        perform_backup(
            config,
            timestamp="20260904T010204Z",
            run_command=fake_run,
        )
    assert not list(config.backup_dir.iterdir())
    assert not config.status_file.exists()


def test_remote_upload_uses_sse_no_public_acl_and_safe_retention(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, local_only=False)
    now = datetime(2026, 9, 4, tzinfo=UTC)
    config.backup_dir.mkdir(parents=True)
    old_local = (
        config.backup_dir
        / "onboardai-postgres-onboard_ai-20260701T000000Z.dump"
    )
    old_local.write_bytes(b"PGDMPold-local")
    old_local_checksum = old_local.with_name(f"{old_local.name}.sha256")
    old_local_checksum.write_text("old")
    commands: list[list[str]] = []
    old = "onboardai/postgres/onboardai-postgres-onboard_ai-20260701T000000Z.dump"
    recent = "onboardai/postgres/onboardai-postgres-onboard_ai-20260903T000000Z.dump"
    unrelated = "onboardai/postgres/customer-unrelated.dump"

    def fake_run(command, **kwargs):
        command = list(command)
        commands.append(command)
        if "pg_dump" in command:
            kwargs["stdout"].write(b"PGDMPremote-payload")
            return _completed(command)
        if "head-object" in command:
            local_path = next(
                Path(item)
                for item in commands[-2]
                if str(item).startswith(str(config.backup_dir))
            )
            return _completed(command, stdout=str(local_path.stat().st_size))
        if "list-objects-v2" in command:
            return _completed(
                command,
                stdout=json.dumps(
                    {
                        "Contents": [
                            {"Key": old},
                            {"Key": f"{old}.sha256"},
                            {"Key": recent},
                            {"Key": unrelated},
                        ]
                    }
                ),
            )
        return _completed(command)

    artifact = perform_backup(
        config,
        timestamp="20260904T000000Z",
        now=now,
        run_command=fake_run,
    )
    upload_commands = [command for command in commands if "cp" in command and "s3" in command]
    assert len(upload_commands) == 2
    assert all("--sse" in command and "AES256" in command for command in upload_commands)
    assert all("--acl" not in command and "public-read" not in command for command in commands)
    deleted = [
        command[command.index("--key") + 1]
        for command in commands
        if "delete-object" in command
    ]
    assert deleted == [old, f"{old}.sha256"]
    assert recent not in deleted and unrelated not in deleted
    marker = json.loads(config.status_file.read_text())
    assert marker["remote_uploaded"] is True
    assert marker["retention_deleted"] == 2
    assert marker["local_retention_deleted"] == 2
    assert not old_local.exists()
    assert not old_local_checksum.exists()
    assert artifact.exists()


def test_upload_failure_is_nonzero_and_keeps_completed_local_dump(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, local_only=False)

    def fake_run(command, **kwargs):
        command = list(command)
        if "pg_dump" in command:
            kwargs["stdout"].write(b"PGDMPupload-failure")
            return _completed(command)
        if "cp" in command and "s3" in command:
            return _completed(command, returncode=1)
        return _completed(command)

    with pytest.raises(BackupError, match="upload failed"):
        perform_backup(
            config,
            timestamp="20260904T020000Z",
            run_command=fake_run,
        )
    assert len(list(config.backup_dir.glob("*.dump"))) == 1
    assert not config.status_file.exists()


def test_backup_main_returns_nonzero_without_printing_password(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "owner-secret-must-not-appear"
    monkeypatch.setenv("ONBOARD_OWNER_PASSWORD", secret)

    def fail_backup(*_args, **_kwargs):
        raise BackupError("simulated dump failure")

    monkeypatch.setattr(backup_module, "perform_backup", fail_backup)
    assert backup_module.main(["--local-only"]) == 1
    output = capsys.readouterr()
    assert secret not in output.out
    assert secret not in output.err
    assert "event=failed" in output.out


def test_retention_recognizer_cannot_select_other_prefix_or_database(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, local_only=False)
    assert _recognized_remote_key(
        config,
        "onboardai/postgres/onboardai-postgres-onboard_ai-20260904T000000Z.dump",
    )
    assert not _recognized_remote_key(
        config,
        "other/onboardai-postgres-onboard_ai-20260904T000000Z.dump",
    )
    assert not _recognized_remote_key(
        config,
        "onboardai/postgres/onboardai-postgres-foreign-20260904T000000Z.dump",
    )
    assert not _recognized_remote_key(config, "onboardai/postgres/unrelated.txt")
