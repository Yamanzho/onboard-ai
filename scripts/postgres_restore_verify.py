#!/usr/bin/env python3
"""Verify an OnboardAI PostgreSQL backup in an isolated pgvector container."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.postgres_backup import BackupError, _write_atomic

RunCommand = Callable[..., subprocess.CompletedProcess[Any]]
_PRODUCTION_TARGETS = {
    "db",
    "onboard-ai-db",
    "onboard-ai_postgres_data",
    "onboard_ai",
}
_VERIFY_CONTAINER_PREFIX = "onboardai-restore-verify-"
_BACKUP_NAME = re.compile(
    r"^onboardai-postgres-[A-Za-z0-9_.-]+-\d{8}T\d{6}Z\.dump$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CORE_TABLES = (
    "alembic_version",
    "companies",
    "employees",
    "assignments",
    "progress",
    "knowledge_articles",
    "knowledge_article_chunks",
    "ai_conversations",
    "ai_messages",
    "idempotency_receipts",
    "telegram_outbound_messages",
)
_RLS_TABLES = (
    "companies",
    "employees",
    "knowledge_article_chunks",
    "ai_conversations",
    "ai_messages",
    "idempotency_receipts",
    "telegram_outbound_messages",
)


class RestoreVerificationError(BackupError):
    """Expected restore-verification failure."""


@dataclass(frozen=True)
class RemoteConfig:
    bucket: str
    prefix: str
    endpoint: str | None
    region: str
    access_key_id: str
    secret_access_key: str

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> RemoteConfig:
        env = os.environ if environ is None else environ
        bucket = env.get("BACKUP_S3_BUCKET", "").strip()
        access_key_id = env.get("BACKUP_S3_ACCESS_KEY_ID", "").strip()
        secret_access_key = env.get("BACKUP_S3_SECRET_ACCESS_KEY", "").strip()
        if not all((bucket, access_key_id, secret_access_key)):
            raise RestoreVerificationError(
                "remote verification requires S3 bucket and credentials"
            )
        endpoint = env.get("BACKUP_S3_ENDPOINT", "").strip() or None
        if endpoint and not endpoint.startswith("https://"):
            raise RestoreVerificationError("BACKUP_S3_ENDPOINT must use HTTPS")
        prefix = env.get(
            "BACKUP_S3_PREFIX", "onboardai/postgres"
        ).strip().strip("/")
        if not prefix or ".." in prefix.split("/"):
            raise RestoreVerificationError("BACKUP_S3_PREFIX is invalid")
        return cls(
            bucket=bucket,
            prefix=f"{prefix}/",
            endpoint=endpoint,
            region=env.get("BACKUP_S3_REGION", "us-east-1").strip() or "us-east-1",
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )


def _log(event: str, **fields: object) -> None:
    rendered = " ".join(f"{key}={value}" for key, value in sorted(fields.items()))
    print(
        f"onboardai_postgres_restore_verify event={event} {rendered}".rstrip(),
        flush=True,
    )


def _run_checked(
    command: Sequence[str],
    *,
    run_command: RunCommand,
    event: str,
    **kwargs: object,
) -> subprocess.CompletedProcess[Any]:
    result = run_command(command, check=False, **kwargs)
    if result.returncode != 0:
        raise RestoreVerificationError(
            f"{event} failed with exit code {result.returncode}"
        )
    return result


def _aws_base(config: RemoteConfig) -> list[str]:
    command = ["aws"]
    if config.endpoint:
        command.extend(["--endpoint-url", config.endpoint])
    command.extend(["--region", config.region])
    return command


def _aws_env(config: RemoteConfig) -> dict[str, str]:
    env = dict(os.environ)
    env["AWS_ACCESS_KEY_ID"] = config.access_key_id
    env["AWS_SECRET_ACCESS_KEY"] = config.secret_access_key
    env["AWS_DEFAULT_REGION"] = config.region
    return env


def _latest_remote_artifact(
    config: RemoteConfig,
    *,
    destination: Path,
    run_command: RunCommand,
) -> tuple[Path, Path]:
    list_command = [
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
        list_command,
        run_command=run_command,
        event="remote_list",
        env=_aws_env(config),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        contents = json.loads(str(result.stdout)).get("Contents", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise RestoreVerificationError("remote object listing is invalid") from exc
    candidates = sorted(
        (
            item["Key"]
            for item in contents
            if isinstance(item, dict)
            and isinstance(item.get("Key"), str)
            and item["Key"].startswith(config.prefix)
            and _BACKUP_NAME.fullmatch(item["Key"].removeprefix(config.prefix))
        ),
        reverse=True,
    )
    if not candidates:
        raise RestoreVerificationError("no recognized remote backup artifact found")
    key = candidates[0]
    artifact = destination / Path(key).name
    checksum = destination / f"{artifact.name}.sha256"
    for remote_key, local_path in ((key, artifact), (f"{key}.sha256", checksum)):
        command = [
            *_aws_base(config),
            "s3",
            "cp",
            f"s3://{config.bucket}/{remote_key}",
            str(local_path),
            "--only-show-errors",
        ]
        _run_checked(
            command,
            run_command=run_command,
            event="remote_download",
            env=_aws_env(config),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        os.chmod(local_path, 0o600)
    _log("download_success", object_key=key)
    return artifact, checksum


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_artifact(artifact: Path, checksum_path: Path) -> tuple[int, str]:
    if not artifact.is_file() or not checksum_path.is_file():
        raise RestoreVerificationError("artifact and checksum sidecar are required")
    size = artifact.stat().st_size
    if size <= 5:
        raise RestoreVerificationError("backup artifact is empty")
    with artifact.open("rb") as stream:
        if stream.read(5) != b"PGDMP":
            raise RestoreVerificationError("artifact is not PostgreSQL custom format")
    try:
        checksum_line = checksum_path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise RestoreVerificationError("checksum sidecar is unreadable") from exc
    parts = checksum_line.split()
    if (
        len(parts) != 2
        or not _SHA256.fullmatch(parts[0])
        or parts[1] != artifact.name
    ):
        raise RestoreVerificationError("checksum sidecar format is invalid")
    actual = _hash_file(artifact)
    if not secrets.compare_digest(parts[0], actual):
        raise RestoreVerificationError("backup checksum mismatch")
    return size, actual


def _safe_container_name(requested: str | None) -> str:
    name = requested or f"{_VERIFY_CONTAINER_PREFIX}{secrets.token_hex(6)}"
    if (
        name in _PRODUCTION_TARGETS
        or not name.startswith(_VERIFY_CONTAINER_PREFIX)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{1,62}", name)
    ):
        raise RestoreVerificationError(
            "verification target must use the disposable restore prefix"
        )
    return name


def _wait_for_postgres(
    container: str,
    *,
    run_command: RunCommand,
    timeout_seconds: float = 60,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = run_command(
            [
                "docker",
                "exec",
                container,
                "pg_isready",
                "--username=postgres",
                "--dbname=onboardai_restore_verify",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode == 0:
            # pg_isready can succeed a fraction before a fresh container accepts
            # the next authenticated session through docker exec.
            time.sleep(1)
            return
        time.sleep(0.5)
    raise RestoreVerificationError("disposable PostgreSQL did not become ready")


def _integrity_sql() -> str:
    table_values = ", ".join(f"'{table}'" for table in _CORE_TABLES)
    rls_values = ", ".join(f"'{table}'" for table in _RLS_TABLES)
    return f"""
DO $verify$
DECLARE
  missing_count integer;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
    RAISE EXCEPTION 'vector extension missing';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public' AND table_name = 'alembic_version'
  ) OR NOT EXISTS (SELECT 1 FROM alembic_version WHERE version_num <> '') THEN
    RAISE EXCEPTION 'Alembic revision missing';
  END IF;
  SELECT count(*) INTO missing_count
  FROM (VALUES {", ".join(f"({value})" for value in table_values.split(", "))}) expected(name)
  WHERE to_regclass('public.' || expected.name) IS NULL;
  IF missing_count <> 0 THEN
    RAISE EXCEPTION 'core tables missing';
  END IF;
  SELECT count(*) INTO missing_count
  FROM (VALUES {", ".join(f"({value})" for value in rls_values.split(", "))}) expected(name)
  LEFT JOIN pg_class c ON c.relname = expected.name
  LEFT JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
  WHERE c.oid IS NULL OR NOT c.relrowsecurity OR NOT c.relforcerowsecurity;
  IF missing_count <> 0 THEN
    RAISE EXCEPTION 'RLS/FORCE RLS verification failed';
  END IF;
  SELECT count(*) INTO missing_count
  FROM (VALUES {", ".join(f"({value})" for value in rls_values.split(", "))}) expected(name)
  WHERE NOT EXISTS (
    SELECT 1 FROM pg_policies p
    WHERE p.schemaname = 'public' AND p.tablename = expected.name
  );
  IF missing_count <> 0 THEN
    RAISE EXCEPTION 'RLS policies missing';
  END IF;
  IF to_regprocedure('app.company_id()') IS NULL
     OR to_regprocedure('app.employee_id()') IS NULL THEN
    RAISE EXCEPTION 'RLS helper functions missing';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'onboard_owner' AND rolbypassrls
  ) OR NOT EXISTS (
    SELECT 1 FROM pg_roles
    WHERE rolname = 'onboard_app' AND NOT rolbypassrls
  ) THEN
    RAISE EXCEPTION 'role RLS attributes invalid';
  END IF;
  IF NOT has_table_privilege('onboard_app', 'public.employees', 'SELECT') THEN
    RAISE EXCEPTION 'runtime table grant missing';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE contype = 'f' AND conrelid IN (
      'public.assignments'::regclass, 'public.progress'::regclass
    )
  ) THEN
    RAISE EXCEPTION 'representative foreign keys missing';
  END IF;
END
$verify$;
SELECT json_build_object(
  'alembic_revision', (SELECT version_num FROM alembic_version LIMIT 1),
  'companies', (SELECT count(*) FROM companies),
  'employees', (SELECT count(*) FROM employees),
  'policies', (SELECT count(*) FROM pg_policies WHERE schemaname IN ('public', 'app'))
)::text;
"""


def _verify_in_container(
    artifact: Path,
    *,
    container: str,
    image: str,
    run_command: RunCommand,
) -> dict[str, object]:
    password = secrets.token_urlsafe(24)
    docker_env = dict(os.environ)
    docker_env["POSTGRES_PASSWORD"] = password
    started = False
    try:
        _run_checked(
            [
                "docker",
                "run",
                "--rm",
                "--detach",
                "--name",
                container,
                "--network",
                "none",
                "-e",
                "POSTGRES_USER=postgres",
                "-e",
                "POSTGRES_PASSWORD",
                "-e",
                "POSTGRES_DB=onboardai_restore_verify",
                image,
            ],
            run_command=run_command,
            event="container_start",
            env=docker_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        started = True
        _wait_for_postgres(container, run_command=run_command)
        role_sql = (
            "CREATE ROLE onboard_owner LOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE BYPASSRLS; "
            "CREATE ROLE onboard_app LOGIN NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOBYPASSRLS;"
        )
        _run_checked(
            [
                "docker",
                "exec",
                container,
                "psql",
                "--username=postgres",
                "--dbname=onboardai_restore_verify",
                "--set=ON_ERROR_STOP=1",
                "--command",
                role_sql,
            ],
            run_command=run_command,
            event="role_setup",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _run_checked(
            ["docker", "cp", str(artifact), f"{container}:/tmp/backup.dump"],
            run_command=run_command,
            event="artifact_copy",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _run_checked(
            [
                "docker",
                "exec",
                container,
                "pg_restore",
                "--list",
                "/tmp/backup.dump",
            ],
            run_command=run_command,
            event="dump_catalog",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        _run_checked(
            [
                "docker",
                "exec",
                container,
                "pg_restore",
                "--username=postgres",
                "--dbname=onboardai_restore_verify",
                "--exit-on-error",
                "/tmp/backup.dump",
            ],
            run_command=run_command,
            event="restore",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        result = _run_checked(
            [
                "docker",
                "exec",
                container,
                "psql",
                "--username=postgres",
                "--dbname=onboardai_restore_verify",
                "--set=ON_ERROR_STOP=1",
                "--tuples-only",
                "--no-align",
                "--command",
                _integrity_sql(),
            ],
            run_command=run_command,
            event="integrity_checks",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            return json.loads(str(result.stdout).strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            raise RestoreVerificationError(
                "integrity checks returned invalid summary"
            ) from exc
    finally:
        if started:
            run_command(
                ["docker", "rm", "--force", container],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )


def verify_backup(
    artifact: Path,
    checksum_path: Path,
    *,
    container_name: str | None = None,
    image: str = "pgvector/pgvector:pg16",
    status_file: Path | None = None,
    run_command: RunCommand = subprocess.run,
) -> dict[str, object]:
    started = time.monotonic()
    container = _safe_container_name(container_name)
    size, checksum = _validate_artifact(artifact, checksum_path)
    _log(
        "start",
        artifact=artifact.name,
        bytes=size,
        checksum_prefix=checksum[:12],
    )
    summary = _verify_in_container(
        artifact,
        container=container,
        image=image,
        run_command=run_command,
    )
    duration = round(time.monotonic() - started, 3)
    marker: dict[str, object] = {
        "artifact": artifact.name,
        "bytes": size,
        "checksum_prefix": checksum[:12],
        "completed_at": datetime.now(UTC).isoformat(),
        "duration_seconds": duration,
        "status": "success",
        "verification": summary,
    }
    if status_file is not None:
        _write_atomic(
            status_file,
            (json.dumps(marker, sort_keys=True) + "\n").encode(),
        )
    _log(
        "success",
        artifact=artifact.name,
        duration_seconds=duration,
        alembic_revision=summary.get("alembic_revision", "unknown"),
    )
    return marker


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--artifact", type=Path)
    source.add_argument("--latest-remote", action="store_true")
    parser.add_argument("--checksum", type=Path)
    parser.add_argument("--confirm-non-production", action="store_true")
    parser.add_argument("--container-name")
    parser.add_argument(
        "--image",
        default="pgvector/pgvector:pg16",
        help="disposable verification image",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    status_file = Path(
        os.environ.get(
            "BACKUP_VERIFY_STATUS_FILE",
            "/var/lib/onboard-ai-backup/last-restore-verification.json",
        )
    )
    if not args.confirm_non_production:
        print(
            "restore verification refused: --confirm-non-production is required",
            file=sys.stderr,
        )
        return 2
    try:
        with tempfile.TemporaryDirectory(prefix="onboardai-restore-download-") as tmp:
            if args.latest_remote:
                artifact, checksum = _latest_remote_artifact(
                    RemoteConfig.from_env(),
                    destination=Path(tmp),
                    run_command=subprocess.run,
                )
            else:
                assert args.artifact is not None
                artifact = args.artifact
                checksum = args.checksum or artifact.with_name(
                    f"{artifact.name}.sha256"
                )
            verify_backup(
                artifact,
                checksum,
                container_name=args.container_name,
                image=args.image,
                status_file=status_file,
            )
    except BackupError as exc:
        _log("failed", error=type(exc).__name__)
        print(f"restore verification failed: {exc}", file=sys.stderr)
        return 1
    except Exception:
        _log("failed", error="unexpected")
        print("restore verification failed: unexpected error", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
