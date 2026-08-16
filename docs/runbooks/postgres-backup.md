# Runbook: PostgreSQL backup and restore (production pilot)

This is an **operator** runbook. OnboardAI does not ship backup infrastructure
inside the application. Do not add backup workers, object-storage clients, or
scheduled jobs to the API.

Production Compose keeps Postgres on the internal network only
(`docker-compose.prod.yml` publishes no DB port). All backup/restore commands
run on the VPS via `docker compose exec`.

Never paste live passwords, dump contents, or encryption keys into tickets,
chat, or git.

Related: [postgres-password-rotation.md](postgres-password-rotation.md).

---

## 1. PostgreSQL backup

Use logical dumps (`pg_dump`) for the pilot. This captures the application
database (schema + data) without copying Redis or container images.

From the compose project directory (typically `/opt/onboard-ai`):

```bash
set -eu
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BACKUP_DIR=/var/backups/onboard-ai
sudo mkdir -p "$BACKUP_DIR"
sudo chmod 700 "$BACKUP_DIR"

# Dump from inside the db container (no host Postgres port in production).
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  pg_dump -U "${POSTGRES_USER:-onboard}" -d "${POSTGRES_DB:-onboard_ai}" \
  --format=custom --file="/tmp/onboard_ai_${STAMP}.dump"

docker compose -f docker-compose.yml -f docker-compose.prod.yml cp \
  "db:/tmp/onboard_ai_${STAMP}.dump" \
  "${BACKUP_DIR}/onboard_ai_${STAMP}.dump"

docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  rm -f "/tmp/onboard_ai_${STAMP}.dump"
```

Custom format (`--format=custom`) is restore-friendly (`pg_restore`) and
compresses better than plain SQL.

Do **not** treat `docker volume backup` / copying `postgres_data` as the primary
method: it is version-sensitive and easy to restore onto the wrong image.

Redis is cache + bot FSM. Do not back it up as source of truth. After restore,
bot sessions re-authenticate via Telegram.

---

## 2. Backup storage

Keep **at least one copy off the VPS**. A dump that only lives on the same disk
as `postgres_data` is lost with the server.

Recommended split:

| Copy | Location | Purpose |
|------|----------|---------|
| Local | `/var/backups/onboard-ai` on the VPS (`mode 700`, root-only) | Fast restore |
| Off-box | Separate object storage / another host / encrypted USB held by ops | Disaster recovery |

Copy off-box with the operator’s existing tool (`scp`, `rclone`, provider CLI).
Do not commit dumps to git.

---

## 3. Encryption

Encrypt dumps **before** they leave the VPS. Age or GnuPG both work. Example
with age (recipient public key stored in the operator’s secret manager):

```bash
age -r "$BACKUP_AGE_RECIPIENT" \
  -o "${BACKUP_DIR}/onboard_ai_${STAMP}.dump.age" \
  "${BACKUP_DIR}/onboard_ai_${STAMP}.dump"
shred -u "${BACKUP_DIR}/onboard_ai_${STAMP}.dump"
```

Store the age identity / GPG private key **outside** the VPS. A key that only
exists on the same host as the ciphertext is not a recovery plan.

Do not encrypt with a passphrase that is also `POSTGRES_PASSWORD` or `SECRET_KEY`.

---

## 4. Retention

Pilot policy (adjust only with an explicit ops decision):

| Age | Action |
|-----|--------|
| Daily | Keep 7 encrypted dumps |
| Weekly | Keep 4 encrypted dumps (one per week) |
| Older | Delete from the VPS **after** confirming the off-box copy exists |

Document the actual job (cron / systemd timer) on the server. This repository
does not install that timer.

---

## 5. Restore

Restoring **replaces** the live database. Take a fresh dump first if the current
volume still has data you might need.

1. Decrypt the chosen dump on an operator workstation or on the VPS into a
   root-only directory.
2. Stop writers:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml stop api bot
   ```

3. Restore into the running `db` container (empty the target database first, or
   restore onto a new volume — do not mix two dumps):

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml cp \
     ./onboard_ai_RESTORE.dump db:/tmp/restore.dump

   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
     pg_restore -U "${POSTGRES_USER:-onboard}" -d "${POSTGRES_DB:-onboard_ai}" \
     --clean --if-exists --no-owner --role=onboard_owner \
     /tmp/restore.dump
   ```

   If `--role=onboard_owner` fails on a particular dump, restore as
   `POSTGRES_USER` then start the API so `bootstrap_rls_roles` re-applies
   `onboard_app` / `onboard_owner` privileges.

4. Remove the plaintext dump from the container:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
     rm -f /tmp/restore.dump
   ```

5. Start API/bot and confirm Super Admin login still works.

Do **not** delete `postgres_data` to “make restore easier” unless you are
intentionally rebuilding from dump onto a new volume. Volume wipe is data loss.

---

## 6. Restore verification

After every restore (including a scheduled drill, not only incidents):

1. `curl -fsS https://<pilot-host>/health` returns `{"status":"ok"}`.
2. Super Admin can log in (`POST /api/v1/super-admin/auth/login`).
3. The pilot company row exists; `company_subscriptions.is_current` is trial or
   active with `ends_at` in the future (or NULL).
4. An invited or active employee can be loaded; invite tokens remain **hashed**
   (`employee_invites.token_hash`) — plaintext tokens must not appear in the dump
   in usable form (they were never stored).
5. HR can open an assignment and see progress rows.
6. Record the drill: dump filename, restore time, who ran it, pass/fail.

Run a restore drill **before** the first real employees join, and at least once
per retention cycle.

---

## What this runbook does not do

- Application-level backup APIs
- WAL-G / Barman / PITR (add later if the pilot outgrows `pg_dump`)
- Redis persistence as a recovery target
- Automatic off-site replication
