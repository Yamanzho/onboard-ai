# Runbook: automated PostgreSQL backup and recovery

This is an operator runbook for the single-VPS production host. Backup and
restore jobs run on the host, not in the API or bot. Repository templates do
not install timers, upload a backup, or touch production automatically.

## Current pilot status

`REMOTE BACKUP: DEFERRED — NOT A PILOT BLOCKER`

`BACKUP/DR: DEFERRED — ACCEPTED PILOT RISK`

Off-host/S3 backup is recommended for later production hardening and is
currently deferred by operator decision. Pilot activation and
`scripts/deploy_production.sh` must not require AWS CLI, `/etc/onboard-ai/backup.env`,
backup timers, or a restore-verification marker.

Do **not** claim RPO 6h active or RTO 4h validated while this status holds.

Accepted residual risk while remote backup remains deferred:

- single VPS;
- no off-host backup;
- no WAL archive / PITR;
- VPS or disk loss can result in unrecoverable production data loss.

Phase 8A scripts, systemd units, and S3 support remain in the repository for
future enablement. Follow the rest of this runbook only when an operator
chooses to turn remote backup on.

Production PostgreSQL is `pgvector/pgvector:pg16`, service `db`, database
`onboard_ai`. The live data volume is selected by Compose (include
`docker-compose.prod.local.yml` when it exists). A copy on that VPS is not
disaster recovery; a valid off-host backup is stored off the VPS.

## Recovery objectives (when remote backup is enabled)

- Target RPO: **6 hours**, once all four daily backup timer runs complete and
  upload successfully. There is no WAL archive/PITR in Phase 8A.
- Target RTO: **4 hours** assuming a replacement VPS, Docker, repository,
  application secrets, and backup credentials are available.
- The RTO is a target after enablement, not a current guarantee. Record
  production-sized drills.
- Restore verification runs daily against the newest remotely stored artifact.

A backup is valid only after an isolated PostgreSQL instance restores it and
passes the automated integrity checks.

## Protection model

The production job creates a PostgreSQL custom-format logical dump using
`onboard_owner`. This role has `BYPASSRLS` and can dump all tenants; never use
`onboard_app`, whose FORCE RLS view may be empty or tenant-scoped.

Artifacts:

```text
onboardai-postgres-onboard_ai-YYYYMMDDTHHMMSSZ.dump
onboardai-postgres-onboard_ai-YYYYMMDDTHHMMSSZ.dump.sha256
```

Custom format is compressed (`--compress=9`) and restore-friendly. The script
writes mode-0600 partial files, fsyncs them, validates the `PGDMP` signature,
atomically renames them, then generates SHA-256. It never treats an S3 ETag as
a checksum.

Off-host storage uses:

- a private S3-compatible bucket;
- HTTPS transport;
- prefix-scoped credentials;
- no public ACL;
- mandatory `AES256` SSE-S3 or configured `aws:kms`;
- dump and SHA-256 sidecar uploaded separately;
- remote size verification before success;
- 30-day prefix-scoped retention by default.

SSE protects storage media but does not hide data from the storage provider.
For an untrusted-provider threat model, add standard client-side `age`
encryption in a later reviewed change and keep its private identity outside
both the VPS and object-storage account. Do not invent cryptography or reuse a
database/application password as an encryption key.

## Prerequisites

AWS CLI, a private bucket, and `/etc/onboard-ai/backup.env` are required only
when enabling Phase 8A. They are **not** current pilot activation
prerequisites.

On the VPS, when you choose to enable remote backup:

1. Docker Engine and Compose plugin (already required by deployment).
2. Python 3.
3. AWS CLI compatible with the chosen S3 endpoint.
4. A private bucket and credential limited to the configured prefix. Required
   actions are ListBucket on the prefix plus GetObject, PutObject, DeleteObject,
   and HeadObject for prefix objects.
5. Bucket public access blocked. Enable bucket versioning/lifecycle protection
   as defense in depth when supported.

Do not store backup credentials in the application `.env`. Create a separate
host-only file:

```bash
sudo install -d -m 700 /etc/onboard-ai
sudo install -m 600 \
  /opt/onboard-ai/deploy/systemd/backup.env.example \
  /etc/onboard-ai/backup.env
sudoedit /etc/onboard-ai/backup.env
```

Replace every placeholder. `BACKUP_S3_ENDPOINT` must be HTTPS. Use `AES256` or
`aws:kms`; the latter also requires `BACKUP_S3_KMS_KEY_ID`.

## Manual backup

Start the same oneshot service used by the timer. `EnvironmentFile` avoids
putting secrets in shell arguments:

```bash
sudo systemctl start onboardai-postgres-backup.service
sudo journalctl -u onboardai-postgres-backup.service --since today
```

For a local drill only, with disposable credentials and database:

```bash
python3 -m scripts.postgres_backup --local-only
```

`--local-only` is not a production backup because it does not survive VPS loss.

## Install scheduling

Review paths first; templates assume `/opt/onboard-ai`.

```bash
sudo install -d -m 700 /var/backups/onboard-ai /var/lib/onboard-ai-backup
sudo install -m 644 deploy/systemd/onboardai-postgres-backup.service \
  deploy/systemd/onboardai-postgres-backup.timer \
  deploy/systemd/onboardai-postgres-restore-verify.service \
  deploy/systemd/onboardai-postgres-restore-verify.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now onboardai-postgres-backup.timer
sudo systemctl enable --now onboardai-postgres-restore-verify.timer
sudo systemctl list-timers 'onboardai-postgres-*'
```

The backup timer runs at 00:15, 06:15, 12:15, and 18:15 UTC with randomized
delay. Restore verification runs daily at 03:30 UTC. `Persistent=true` runs a
missed job after host recovery. Application deploy/restart does not control
either schedule.

## Automated restore verification

The verification service:

1. Lists only recognized objects below `BACKUP_S3_PREFIX`.
2. Downloads the newest dump and matching checksum to a private temporary dir.
3. Verifies non-empty size, SHA-256, and `PGDMP` signature.
4. Creates a uniquely named, unpublished, network-isolated
   `pgvector/pgvector:pg16` container.
5. Refuses production names and requires `--confirm-non-production`.
6. Creates disposable `onboard_owner`/`onboard_app` roles.
7. Runs `pg_restore --list`, restores with `--exit-on-error`, and checks:
   - readable Alembic revision;
   - `vector` extension;
   - core application tables and row-count queries;
   - RLS helper functions and policies;
   - RLS and FORCE RLS flags;
   - `onboard_owner` BYPASSRLS and `onboard_app` NOBYPASSRLS;
   - runtime table grants;
   - representative foreign keys.
8. Removes the disposable container and temporary download on every outcome.

Manual local verification:

```bash
python3 -m scripts.postgres_restore_verify \
  --artifact /safe/path/onboardai-postgres-onboard_ai-YYYYMMDDTHHMMSSZ.dump \
  --checksum /safe/path/onboardai-postgres-onboard_ai-YYYYMMDDTHHMMSSZ.dump.sha256 \
  --confirm-non-production
```

Do not rename a production container to bypass the guard. This command never
restores into an existing database or volume.

## Retention

`BACKUP_RETENTION_DAYS=30` retains recognized daily artifacts for 30 days.
Deletion occurs only after the current dump and checksum both upload and pass
remote size checks. The same prefix/name/age guard prunes completed local
artifacts so the VPS backup directory does not grow without bound. The current
pair is excluded.

Only keys matching this shape beneath the configured prefix are eligible:

```text
onboardai-postgres-<configured-database>-YYYYMMDDTHHMMSSZ.dump[.sha256]
```

Unrelated bucket objects are ignored. A retention failure logs
`event=retention_warning` but does not invalidate an already uploaded backup.
Provider lifecycle policy may be configured as additional protection, but must
not retain fewer objects than the documented RPO/retention policy.

## Status and future alerts

Stable logs begin with:

```text
onboardai_postgres_backup event=...
onboardai_postgres_restore_verify event=...
```

Success markers (mode 0600):

```text
/var/lib/onboard-ai-backup/last-backup.json
/var/lib/onboard-ai-backup/last-restore-verification.json
```

Phase 8B monitoring can alert on the following **only after**
`ONBOARDAI_BACKUP_ENFORCEMENT=1` is set (after S3 config, a successful remote
backup, restore verification, and timers). While enforcement is `0` or unset,
these backup/restore alerts stay silent so an intentionally deferred backup
does not page the pilot:

- non-zero systemd service result;
- no successful remote backup marker for more than 8 hours
  (6-hour schedule plus 2 hours of timer/runtime slack);
- no successful restore-verification marker for more than 36 hours
  (daily schedule plus 12 hours of timer/runtime slack);
- `event=retention_warning`;
- artifact/checksum/restore/integrity failure.

Logs include timestamps, artifact/object names, byte size, checksum prefix,
duration, and outcomes. They must never include database URLs, passwords,
access keys, dump contents, prompts, or application row values.

## Failure behavior

| Failure | Backup valid? | Exit | Operator action |
|---|---:|---:|---|
| PostgreSQL unavailable or `pg_dump` fails | No | non-zero | Check `docker compose ps db`, storage, role password; retry |
| Local disk full/write/fsync failure | No | non-zero | Free space, remove only known old artifacts; retry |
| Empty/wrong-format artifact | No | non-zero | Inspect PostgreSQL/container logs; retry |
| Checksum creation/mismatch | No | non-zero | Discard artifact pair and rerun |
| Remote unavailable/upload timeout | No off-host backup | non-zero | Keep local completed dump, fix network/credentials, rerun |
| Remote size mismatch | No | non-zero | Remove bad remote object and rerun |
| Retention cleanup failure after upload | Yes | zero with warning | Review prefix and clean up safely |
| Restore verification failure | Backup unverified | non-zero | Preserve evidence, test previous artifact, investigate immediately |

Incomplete `.partial` files are removed. A completed local artifact is retained
when remote upload fails so an operator can retry/recover it.

## Full VPS-loss recovery

Do not start API/bot writers before database restoration.

1. Provision a new host and install Docker/Compose.
2. Clone the reviewed repository revision.
3. Restore application and backup credentials from the secret manager. Backup
   restoration does not recover `SECRET_KEY`, Telegram/OpenAI tokens, SMTP
   credentials, or object-storage credentials.
4. Create a fresh PostgreSQL volume; do not attach an unknown old volume.
5. Start only PostgreSQL:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d db
   ```

6. Download the latest **successfully restore-verified** dump and checksum.
   Validate SHA-256 before restore.
7. Bootstrap roles/extensions without starting the normal API entrypoint:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm \
     --no-deps --entrypoint python api -m scripts.bootstrap_rls_roles
   ```

8. Copy the dump to `db` and restore as the bootstrap superuser. The logical
   dump preserves schema ownership, grants, policies, RLS, and data:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml cp \
     ./onboardai-postgres-RESTORE.dump db:/tmp/restore.dump
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
     pg_restore -U "${POSTGRES_USER:-onboard}" \
       -d "${POSTGRES_DB:-onboard_ai}" --clean --if-exists --exit-on-error \
       /tmp/restore.dump
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
     rm -f /tmp/restore.dump
   ```

9. Read the restored revision before upgrading:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
     psql -U "${POSTGRES_USER:-onboard}" -d "${POSTGRES_DB:-onboard_ai}" \
       -c 'TABLE alembic_version'
   ```

10. Run `alembic upgrade head` only if deploying application code newer than
    the restored revision. Do not silently upgrade during basic verification.
11. Start API, Redis, frontend, and bot; check `/ready`, Super Admin login,
    tenant access, Telegram authentication, and the production golden path.
12. Record artifact, checksum prefix, dump/restore/verification durations,
    operator, and outcome.

Redis contains cache/FSM/session-pointer state and is not the PostgreSQL source
of truth. Users/bot sessions may need to authenticate again.

## Credential compromise

A database restore does not make compromised external credentials safe. Rotate
affected database, JWT, bot, OpenAI, SMTP, and storage credentials through
their dedicated procedures. Do not overwrite restored database state merely to
rotate a role password.

## Not provided by Phase 8A

- WAL archiving or point-in-time recovery;
- high availability or automatic failover;
- managed PostgreSQL;
- Redis disaster recovery;
- automatic installation on production;
- client-side encryption/key escrow.
