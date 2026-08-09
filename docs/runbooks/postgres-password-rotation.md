# Runbook: PostgreSQL password rotation (production)

**Finding F-03.** This runbook prevents a common operational mistake:
changing `POSTGRES_PASSWORD` in `.env` on an **existing** `postgres_data` volume
does **not** rotate the PostgreSQL role password.

PostgreSQL applies `POSTGRES_PASSWORD` **only during first database initialization**
(empty data directory). After that, the env var is ignored by the official image.

Do **not** delete the production `postgres_data` volume to “rotate” a password.
That destroys data. Use `ALTER ROLE` (below) instead.

Never paste real passwords into tickets, chat, or commits. Generate secrets locally
and store them in your secret manager / host `.env` (mode `600`).

---

## Roles in this project

| Role | Purpose | Env that must match the live role password |
|------|---------|--------------------------------------------|
| `POSTGRES_USER` (default `onboard`) | Bootstrap superuser (creates roles, used by `BOOTSTRAP_DATABASE_URL`) | `POSTGRES_PASSWORD` |
| `onboard_owner` | Migrator / owner (`BYPASSRLS`); `MIGRATION_DATABASE_URL` | `ONBOARD_OWNER_PASSWORD` |
| `onboard_app` | Runtime app role (`NOBYPASSRLS`); `DATABASE_URL` | `ONBOARD_APP_PASSWORD` |

Compose production builds URLs from these env vars (`docker-compose.prod.yml`).

---

## 1. Fresh deployment (empty volume)

1. Generate strong unique values (≥ 12 chars; not documented defaults such as `onboard`).
2. Set `POSTGRES_PASSWORD`, `ONBOARD_OWNER_PASSWORD`, and `ONBOARD_APP_PASSWORD` in `.env`.
3. Start with production Compose. On first boot the official Postgres image creates
   `POSTGRES_USER` with `POSTGRES_PASSWORD`.
4. API entrypoint runs `python -m scripts.bootstrap_rls_roles`, which creates/updates
   `onboard_owner` / `onboard_app` passwords from `ONBOARD_*_PASSWORD`, then runs migrations.

No extra rotation step is required on a brand-new volume.

---

## 2. Existing `postgres_data` volume — what env edits do

| Change in `.env` | Effect on an **already initialized** volume |
|------------------|-----------------------------------------------|
| `POSTGRES_PASSWORD=…` | **Does not** change the live bootstrap role password. Containers may fail to bootstrap/connect if the env no longer matches the DB. |
| `ONBOARD_APP_PASSWORD` / `ONBOARD_OWNER_PASSWORD` | On next API start, `bootstrap_rls_roles` runs `ALTER ROLE … PASSWORD` for `onboard_app` / `onboard_owner` (idempotent). Still update `.env` **before** recreate so URLs match. |

**Changing `.env` ≠ rotating the bootstrap (`POSTGRES_USER`) password.**

---

## 3. Rotate application DB passwords (`onboard_app` / `onboard_owner`)

Preferred path (no volume wipe):

1. **Backup** the database (see §8).
2. Generate new `ONBOARD_APP_PASSWORD` and/or `ONBOARD_OWNER_PASSWORD`.
3. Update `.env` (and any external secret store) with the new values.
4. Recreate the API container so entrypoint re-runs bootstrap:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate api
   ```

5. Confirm API health via the edge/frontend path (API has no published host port in prod):

   ```bash
   curl -sS http://127.0.0.1:3000/health
   ```

6. Confirm roles accept the new passwords (example — use your values, do not log them):

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
     psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c '\du'
   ```

   Then connect as each role using the new password from a one-off client
   (or temporarily via `docker compose exec` with `PGPASSWORD` from your secret store — never `echo` passwords into shell history if avoidable).

---

## 4. Rotate bootstrap role password (`POSTGRES_USER` / `POSTGRES_PASSWORD`)

Required when the bootstrap superuser password must change on an **existing** volume.

1. **Backup** first (§8).
2. Generate a new password; keep the old value available until verification succeeds.
3. Apply the change **inside PostgreSQL** (data-preserving). Prefer the interactive
   `\password` prompt so the secret never appears on the process argv:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -it db \
     psql -U onboard -d onboard_ai
   # inside psql:
   \password onboard
   ```

   Non-interactive alternative (password already in shell env `NEW_PW` from a secret
   manager; passed as a `psql` variable with `:''` quoting — same idea as
   `quote_literal` in `scripts/bootstrap_rls_roles.py`):

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
     psql -U onboard -d onboard_ai -v ON_ERROR_STOP=1 \
     -v "pw=${NEW_PW}" \
     -c "ALTER ROLE onboard PASSWORD :'pw'"
   ```

   Clear `NEW_PW` from the shell afterward. Do not commit password files.

4. Update `.env`: set `POSTGRES_PASSWORD` (and `BOOTSTRAP_DATABASE_URL` if you maintain
   it by hand) to the **same** new value.
5. Recreate API (and any process using the bootstrap URL):

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --force-recreate api
   ```

6. Verify (§6).

---

## 5. Rotate without deleting production data

Allowed:

- `ALTER ROLE … PASSWORD …`
- Updating `.env` / secret store to match
- Recreating **application** containers

Not allowed as the primary procedure:

- `docker compose down -v` / deleting `postgres_data`
- Recreating the DB volume “to pick up POSTGRES_PASSWORD”

Volume deletion is disaster recovery / decommission only — not password rotation.

---

## 6. Verification after rotation

1. `docker compose … ps` — `db` and `api` healthy.
2. `curl -sS http://127.0.0.1:3000/health` → `{"status":"ok"}` (via frontend; not public API).
3. API logs show successful bootstrap + migrations (no authentication failures to Postgres).
4. Login to Admin UI / Super Admin still works.
5. Optional: `SELECT current_user;` as `onboard_app` and `onboard_owner` with the new passwords.

---

## 7. Rollback considerations

- Keep the previous passwords in a secure rollback envelope until verification passes.
- If `.env` was updated but `ALTER ROLE` was not (bootstrap role), revert `.env` to the
  live DB password and recreate API — do not “fix” by wiping the volume.
- If `ALTER ROLE` succeeded but `.env` is wrong, fix `.env` to the new password and
  recreate API.
- Application role passwords: restoring old `ONBOARD_*_PASSWORD` in `.env` and
  recreating API re-applies those passwords via bootstrap `ALTER ROLE`.

---

## 8. Backup requirement

Before any production password rotation:

```bash
# Example logical backup (adjust names; store the dump offline with restricted ACL)
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db \
  pg_dump -U onboard -d onboard_ai -Fc > "onboard_ai_pre_rotation_$(date -u +%Y%m%dT%H%M%SZ).dump"
```

Confirm the dump is non-empty and readable before proceeding. Practice restore on staging.

---

## 9. Summary: env change vs real rotation

| Goal | Sufficient action |
|------|-------------------|
| New empty volume | Set env once; first Postgres init + API bootstrap |
| Rotate `onboard_app` / `onboard_owner` | Update `ONBOARD_*_PASSWORD` → recreate API (bootstrap `ALTER ROLE`) |
| Rotate bootstrap `POSTGRES_USER` | **`ALTER ROLE` in Postgres** + update `POSTGRES_PASSWORD` in `.env` → recreate API |
| “I only edited `POSTGRES_PASSWORD` in `.env`” | **Not a rotation** on an existing volume — fix env or run §4 |
