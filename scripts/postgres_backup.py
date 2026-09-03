#!/usr/bin/env python3
"""Host-operated PostgreSQL backup for the OnboardAI production pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

RunCommand = Callable[..., subprocess.CompletedProcess[Any]]
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}$")
_TIMESTAMP = re.compile(r"^\d{8}T\d{6}Z$")
_SSE_VALUES = {"AES256", "aws:kms"}


class BackupError(RuntimeError):
    """Expected operator-facing backup failure."""


@dataclass(frozen=True)
class BackupConfig:
    compose_dir: Path
    backup_dir: Path
    status_file: Path
    database: str
    owner_password: str
    source_container: str | None
    bucket: str | None
    prefix: str
    endpoint: str | None
    region: str
    access_key_id: str | None
    secret_access_key: str | None
    sse: str
    kms_key_id: str | None
    retention_days: int
    local_only: bool

    @classmethod
    def from_env(
        cls,
        *,
        local_only: bool,
        environ: Mapping[str, str] | None = None,
    ) -> BackupConfig:
        env = os.environ if environ is None else environ
        database = env.get("POSTGRES_DB", "onboard_ai").strip()
        if not _SAFE_NAME.fullmatch(database):
            raise BackupError("POSTGRES_DB contains unsupported characters")
        owner_password = env.get("ONBOARD_OWNER_PASSWORD", "")
        if not owner_password:
            raise BackupError("ONBOARD_OWNER_PASSWORD is required")

        retention_raw = env.get("BACKUP_RETENTION_DAYS", "30")
        try:
            retention_days = int(retention_raw)
        except ValueError as exc:
            raise BackupError("BACKUP_RETENTION_DAYS must be an integer") from exc
        if retention_days < 1 or retention_days > 3650:
            raise BackupError("BACKUP_RETENTION_DAYS must be between 1 and 3650")

        endpoint = env.get("BACKUP_S3_ENDPOINT", "").strip() or None
        if endpoint is not None and not endpoint.startswith("https://"):
            raise BackupError("BACKUP_S3_ENDPOINT must use HTTPS")
        sse = env.get("BACKUP_S3_SSE", "AES256").strip()
        if sse not in _SSE_VALUES:
            raise BackupError("BACKUP_S3_SSE must be AES256 or aws:kms")
        kms_key_id = env.get("BACKUP_S3_KMS_KEY_ID", "").strip() or None
        if sse == "aws:kms" and not kms_key_id:
            raise BackupError("BACKUP_S3_KMS_KEY_ID is required for aws:kms")

        bucket = env.get("BACKUP_S3_BUCKET", "").strip() or None
        access_key_id = env.get("BACKUP_S3_ACCESS_KEY_ID", "").strip() or None
        secret_access_key = (
            env.get("BACKUP_S3_SECRET_ACCESS_KEY", "").strip() or None
        )
        if not local_only and not all(
            (bucket, access_key_id, secret_access_key)
        ):
            raise BackupError(
                "remote backup requires BACKUP_S3_BUCKET and S3 credentials"
            )

        prefix = env.get(
            "BACKUP_S3_PREFIX", "onboardai/postgres"
        ).strip().strip("/")
        if not prefix or ".." in prefix.split("/"):
            raise BackupError("BACKUP_S3_PREFIX must be a safe non-empty prefix")

        backup_dir = Path(
            env.get("BACKUP_LOCAL_DIR", "/var/backups/onboard-ai")
        ).expanduser()
        status_file = Path(
            env.get(
                "BACKUP_STATUS_FILE",
                "/var/lib/onboard-ai-backup/last-backup.json",
            )
        ).expanduser()
        source_container = env.get("BACKUP_SOURCE_CONTAINER", "").strip() or None
        if source_container and not _SAFE_NAME.fullmatch(source_container):
            raise BackupError("BACKUP_SOURCE_CONTAINER contains unsupported characters")

        return cls(
            compose_dir=Path(
                env.get("BACKUP_COMPOSE_DIR", "/opt/onboard-ai")
            ).expanduser(),
            backup_dir=backup_dir,
            status_file=status_file,
            database=database,
            owner_password=owner_password,
            source_container=source_container,
            bucket=bucket,
            prefix=f"{prefix}/",
            endpoint=endpoint,
            region=env.get("BACKUP_S3_REGION", "us-east-1").strip() or "us-east-1",
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            sse=sse,
            kms_key_id=kms_key_id,
            retention_days=retention_days,
            local_only=local_only,
        )


def _log(event: str, **fields: object) -> None:
    rendered = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    print(f"onboardai_postgres_backup event={event} {rendered}".rstrip(), flush=True)


def _artifact_name(database: str, timestamp: str) -> str:
    if not _SAFE_NAME.fullmatch(database) or not _TIMESTAMP.fullmatch(timestamp):
        raise BackupError("invalid artifact identity")
    return f"onboardai-postgres-{database}-{timestamp}.dump"


def _dump_command(config: BackupConfig) -> list[str]:
    pg_dump = [
        "pg_dump",
        "--host=127.0.0.1",
        "--port=5432",
        "--username=onboard_owner",
        f"--dbname={config.database}",
        "--format=custom",
        "--compress=9",
        "--no-password",
    ]
    if config.source_container:
        return [
            "docker",
            "exec",
            "-e",
            "PGPASSWORD",
            config.source_container,
            *pg_dump,
        ]
    return [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
        "exec",
        "-T",
        "-e",
        "PGPASSWORD",
        "db",
        *pg_dump,
    ]


def _aws_base(config: BackupConfig) -> list[str]:
    command = ["aws"]
    if config.endpoint:
        command.extend(["--endpoint-url", config.endpoint])
    command.extend(["--region", config.region])
    return command


def _aws_env(config: BackupConfig) -> dict[str, str]:
    env = dict(os.environ)
    if config.access_key_id:
        env["AWS_ACCESS_KEY_ID"] = config.access_key_id
    if config.secret_access_key:
        env["AWS_SECRET_ACCESS_KEY"] = config.secret_access_key
    env["AWS_DEFAULT_REGION"] = config.region
    return env


def _sse_args(config: BackupConfig) -> list[str]:
    result = ["--sse", config.sse]
    if config.sse == "aws:kms":
        assert config.kms_key_id is not None
        result.extend(["--sse-kms-key-id", config.kms_key_id])
    return result


def _run_checked(
    command: Sequence[str],
    *,
    run_command: RunCommand,
    event: str,
    **kwargs: object,
) -> subprocess.CompletedProcess[Any]:
    result = run_command(command, check=False, **kwargs)
    if result.returncode != 0:
        raise BackupError(f"{event} failed with exit code {result.returncode}")
    return result


def _validate_dump(path: Path) -> int:
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            magic = stream.read(5)
    except OSError as exc:
        raise BackupError("could not read backup artifact") from exc
    if size <= 5 or magic != b"PGDMP":
        raise BackupError("backup artifact is empty or not PostgreSQL custom format")
    return size


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_atomic(path: Path, content: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    partial = path.with_name(f".{path.name}.partial")
    try:
        descriptor = os.open(
            partial,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            mode,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
        os.chmod(path, mode)
    finally:
        partial.unlink(missing_ok=True)


def _remote_key(config: BackupConfig, filename: str) -> str:
    return f"{config.prefix}{filename}"


def _upload_one(
    config: BackupConfig,
    path: Path,
    *,
    checksum: str,
    run_command: RunCommand,
) -> str:
    assert config.bucket is not None
    key = _remote_key(config, path.name)
    destination = f"s3://{config.bucket}/{key}"
    command = [
        *_aws_base(config),
        "s3",
        "cp",
        str(path),
        destination,
        "--only-show-errors",
        "--metadata",
        f"sha256={checksum},database={config.database}",
        *_sse_args(config),
    ]
    _run_checked(
        command,
        run_command=run_command,
        event="upload",
        env=_aws_env(config),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    head = [
        *_aws_base(config),
        "s3api",
        "head-object",
        "--bucket",
        config.bucket,
        "--key",
        key,
        "--query",
        "ContentLength",
        "--output",
        "text",
    ]
    result = _run_checked(
        head,
        run_command=run_command,
        event="upload_verify",
        env=_aws_env(config),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        remote_size = int(str(result.stdout).strip())
    except ValueError as exc:
        raise BackupError("remote storage returned an invalid object size") from exc
    if remote_size != path.stat().st_size:
        raise BackupError("uploaded object size does not match local artifact")
    return key


def _recognized_remote_key(config: BackupConfig, key: str) -> bool:
    prefix = re.escape(config.prefix)
    database = re.escape(config.database)
    pattern = (
        rf"^{prefix}onboardai-postgres-{database}-\d{{8}}T\d{{6}}Z"
        rf"\.dump(?:\.sha256)?$"
    )
    return re.fullmatch(pattern, key) is not None


def _parse_remote_timestamp(config: BackupConfig, key: str) -> datetime:
    stem = key.removesuffix(".sha256")
    match = re.search(r"-(\d{8}T\d{6}Z)\.dump$", stem)
    if not match or not _recognized_remote_key(config, key):
        raise BackupError("unrecognized backup object key")
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _prune_remote(
    config: BackupConfig,
    *,
    current_keys: set[str],
    now: datetime,
    run_command: RunCommand,
) -> int:
    assert config.bucket is not None
    listing = [
        *_aws_base(config),
        "s3api",
        "list-objects-v2",
        "--bucket",
        config.bucket,
        "--prefix",
        config.prefix,
        "--output",
        "json",
    ]
    result = _run_checked(
        listing,
        run_command=run_command,
        event="retention_list",
        env=_aws_env(config),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        payload = json.loads(str(result.stdout))
    except json.JSONDecodeError as exc:
        raise BackupError("remote retention listing was not valid JSON") from exc
    cutoff = now - timedelta(days=config.retention_days)
    expired: list[str] = []
    for item in payload.get("Contents", []):
        key = item.get("Key")
        if (
            isinstance(key, str)
            and key not in current_keys
            and _recognized_remote_key(config, key)
            and _parse_remote_timestamp(config, key) < cutoff
        ):
            expired.append(key)
    for key in sorted(expired):
        delete = [
            *_aws_base(config),
            "s3api",
            "delete-object",
            "--bucket",
            config.bucket,
            "--key",
            key,
        ]
        _run_checked(
            delete,
            run_command=run_command,
            event="retention_delete",
            env=_aws_env(config),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _log("retention_deleted", object_key=key)
    return len(expired)


def _prune_local(
    config: BackupConfig,
    *,
    current_paths: set[Path],
    now: datetime,
) -> int:
    cutoff = now - timedelta(days=config.retention_days)
    deleted = 0
    for path in config.backup_dir.iterdir():
        if path in current_paths or not path.is_file():
            continue
        key = _remote_key(config, path.name)
        if (
            _recognized_remote_key(config, key)
            and _parse_remote_timestamp(config, key) < cutoff
        ):
            path.unlink()
            deleted += 1
            _log("local_retention_deleted", artifact=path.name)
    return deleted


def perform_backup(
    config: BackupConfig,
    *,
    timestamp: str | None = None,
    now: datetime | None = None,
    run_command: RunCommand = subprocess.run,
) -> Path:
    started = time.monotonic()
    current_time = now or datetime.now(UTC)
    stamp = timestamp or current_time.strftime("%Y%m%dT%H%M%SZ")
    artifact_name = _artifact_name(config.database, stamp)
    final_path = config.backup_dir / artifact_name
    partial_path = config.backup_dir / f".{artifact_name}.partial"
    checksum_path = final_path.with_name(f"{final_path.name}.sha256")
    config.backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(config.backup_dir, 0o700)
    _log("start", database=config.database, timestamp=stamp)

    dump_env = dict(os.environ)
    dump_env["PGPASSWORD"] = config.owner_password
    try:
        descriptor = os.open(
            partial_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as output:
            _run_checked(
                _dump_command(config),
                run_command=run_command,
                event="pg_dump",
                cwd=config.compose_dir,
                env=dump_env,
                stdout=output,
                stderr=subprocess.PIPE,
            )
            output.flush()
            os.fsync(output.fileno())
        _validate_dump(partial_path)
        os.replace(partial_path, final_path)
        os.chmod(final_path, 0o600)
        size = _validate_dump(final_path)
        checksum = _sha256(final_path)
        _write_atomic(
            checksum_path,
            f"{checksum}  {final_path.name}\n".encode(),
        )

        object_key = ""
        retention_deleted = 0
        local_retention_deleted = 0
        retention_result = "not_run"
        if not config.local_only:
            object_key = _upload_one(
                config,
                final_path,
                checksum=checksum,
                run_command=run_command,
            )
            checksum_key = _upload_one(
                config,
                checksum_path,
                checksum=checksum,
                run_command=run_command,
            )
            _log("upload_success", object_key=object_key)
            try:
                retention_deleted = _prune_remote(
                    config,
                    current_keys={object_key, checksum_key},
                    now=current_time,
                    run_command=run_command,
                )
                local_retention_deleted = _prune_local(
                    config,
                    current_paths={final_path, checksum_path},
                    now=current_time,
                )
                retention_result = "success"
            except (BackupError, OSError):
                retention_result = "warning"
                _log("retention_warning")

        duration = round(time.monotonic() - started, 3)
        marker = {
            "artifact": final_path.name,
            "bytes": size,
            "checksum_prefix": checksum[:12],
            "completed_at": current_time.isoformat(),
            "duration_seconds": duration,
            "object_key": object_key,
            "remote_uploaded": not config.local_only,
            "retention_deleted": retention_deleted,
            "local_retention_deleted": local_retention_deleted,
            "retention_result": retention_result,
            "status": "success",
        }
        _write_atomic(
            config.status_file,
            (json.dumps(marker, sort_keys=True) + "\n").encode(),
        )
        _log(
            "success",
            artifact=final_path.name,
            bytes=size,
            checksum_prefix=checksum[:12],
            duration_seconds=duration,
            remote_uploaded=not config.local_only,
        )
        return final_path
    except Exception:
        partial_path.unlink(missing_ok=True)
        if not final_path.exists():
            checksum_path.unlink(missing_ok=True)
        raise


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="create a local artifact without off-host upload (CI/drills only)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = BackupConfig.from_env(local_only=args.local_only)
        perform_backup(config)
    except BackupError as exc:
        _log("failed", error=type(exc).__name__)
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        _log("failed", error="unexpected")
        print("backup failed: unexpected error", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
