# Production pilot golden path

End-to-end checklist for the first production tenant. Production uses a
**shared Telegram bot**: identity is `telegram_user_id` → Employee →
`employee.company_id`. `BOT_COMPANY_ID` is optional ops metadata, not tenant
authority. Do not enable `SEED_DEMO`.

Public topology: `Internet → HTTPS nginx → frontend → /api → FastAPI → PostgreSQL / Redis`.

Invite tokens live in the URL **fragment** (`/invite#<token>`). They are stored
hashed (`employee_invites.token_hash`). Logs must never print the raw token.

Automated coverage of this flow (API + bot invite-accept boundary, no live
Telegram Bot API): `tests/e2e/test_golden_path.py`. Cross-tenant isolation:
`tests/e2e/test_tenant_isolation.py`.

---

## 0. Preconditions (ops)

| Check | Expected |
|-------|----------|
| Compose | `docker compose -f docker-compose.yml -f docker-compose.prod.yml` |
| Env | `APP_ENV=production`, `DEBUG=false`, `SEED_DEMO=false` |
| Secrets | Unique `SECRET_KEY`, `SUPER_ADMIN_PASSWORD`, `POSTGRES_PASSWORD`, `ONBOARD_OWNER_PASSWORD`, `ONBOARD_APP_PASSWORD`, `REDIS_PASSWORD`, `BOT_SERVICE_TOKEN` |
| AI | `AI_EMBEDDING_PROVIDER=openai`, `AI_LLM_PROVIDER=openai`, hosted API key; both `AI_ALLOW_FAKE_*_IN_PRODUCTION` flags false |
| URLs | `INVITE_BASE_URL=https://<pilot-host>` |
| TLS | Host nginx HTTPS site (`deploy/nginx/onboardai.aoe.kz.https.conf`) |
| SMTP | `SMTP_*` set **or** operator ready to copy `invite_url` manually |
| Bot | `BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, matching `BOT_SERVICE_TOKEN`. Leave `BOT_COMPANY_ID` empty |

The API can start without `BOT_COMPANY_ID`. Create the company after Super
Admin login. Never set `BOT_COMPANY_ID` to the demo seed UUID
`11111111-1111-4111-8111-111111111111`. Tenant membership always comes from
the bound employee row, not this variable.

---

## 1. Super Admin login

| | |
|--|--|
| **Expected** | Platform session cookies set; redirect to `/platform` |
| **API** | `POST /api/v1/super-admin/auth/login` `{email, password}` |
| **UI** | `/platform/login` (alias `/super-admin/login`) |
| **DB** | `super_admins.last_login_at` updated; `refresh_sessions` row for `super_admin` |
| **Security** | Rate-limited by IP. Tenant JWTs cannot call this. Password never returned. `Secure` + `HttpOnly` cookies |

---

## 2. Create company

| | |
|--|--|
| **Expected** | Company + invited Admin + **trial** subscription (starter, 14 days, employee_limit=10, program_limit=3) |
| **API** | `POST /api/v1/super-admin/companies` |
| **UI** | `/platform/companies/new` |
| **DB** | `companies` row `is_active=true`; `employees` admin `status=invited`; `company_subscriptions` `status=trial` `is_current=true`; `employee_invites` hashed token; `platform_audit_logs` `company_created` |
| **Security** | Super Admin only. Tenant Admin cannot create companies. Cross-tenant ids are not accepted here |

Copy `id` from the response for later tenant operations. It is **not**
required as `BOT_COMPANY_ID`.

---

## 3. Create Admin (done in step 2)

Company create already invites the Admin. If you must re-invite:

| | |
|--|--|
| **Expected** | New invite; previous unused invites invalidated |
| **API** | `POST /api/v1/super-admin/companies/{company_id}/users/{employee_id}/resend-invite` |
| **UI** | Company detail → resend invite |
| **DB** | New `employee_invites` row; old unused `used_at`/`invalidated` |
| **Security** | Raw token only in `invite_url` fragment (and email body if SMTP). Response may include `invite_url` when delivery is `manual_url` |

---

## 4. Admin accepts invite and logs in

| | |
|--|--|
| **Expected** | Admin `status=active`, password hash set, can open `/company` |
| **API** | `POST /api/v1/auth/invite/preview` then `POST /api/v1/auth/invite/accept`; then `POST /api/v1/auth/login` |
| **UI** | `/invite#<token>` → set password → `/login` → `/company` |
| **DB** | `employees.status=active`, `password_hash` Argon2id; invite `used_at` set; sibling invites invalidated |
| **Security** | Replay of the same token fails. Expired token (`INVITE_TTL_HOURS`, default 24h) fails. Token not in path (fragment). Archived employee cannot accept |

---

## 5. Create HR

| | |
|--|--|
| **Expected** | HR user `status=invited`; invite delivery truthful (`email` or `manual_url`) |
| **API** | `POST /api/v1/employees` `{role: "hr", status: "invited", email, full_name, company_id}` |
| **UI** | `/company/hr/create` |
| **DB** | `employees.role=hr` `status=invited`; invite purpose `hr`; subscription employee count +1 |
| **Security** | Caller must be Admin of **this** company. Peer-company Admin → 404. Employee limit enforced. HR cannot create another HR via this Admin-only route |

HR then accepts invite (same accept APIs as step 4) and logs in → `/hr`.

---

## 6. Create Employee

| | |
|--|--|
| **Expected** | Employee `status=invited`; web invite URL and/or Telegram deep link |
| **API** | `POST /api/v1/employees` `{role: "employee", status: "invited", email, ...}` |
| **UI** | `/hr/employees/new` |
| **DB** | `employees.role=employee` `status=invited`; invite purpose `employee`; `telegram_invite_url` only if `TELEGRAM_BOT_USERNAME` is set |
| **Security** | HR/Admin same company only. Cannot create `status=active` via tenant API (must accept invite). Duplicate email / telegram_user_id → 409. Employee limit fail-closed |

Delivery:

- SMTP configured and send succeeds → `invite_email_sent=true`, `invite_delivery=email`, `invite_url` omitted from JSON.
- SMTP unset or send fails → `invite_email_sent=false`, `invite_delivery=manual_url`, `invite_url` present for the operator to copy. Logs do **not** include the raw token.

---

## 7. Invite (SMTP or manual URL)

| | |
|--|--|
| **Expected** | Employee receives mail **or** HR copies `invite_url` / `telegram_invite_url` |
| **API** | Create response fields above; optional `POST /api/v1/employees/{id}/resend-invite` |
| **UI** | Employee detail shows delivery status; copy link when manual |
| **DB** | Unchanged except resend invalidates prior unused invites |
| **Security** | Fragment URL (`/invite#token`). Telegram link `https://t.me/<bot>?start=<token>` (token ≤ 64 chars). Do not paste tokens into logs, tickets, or screenshots |

---

## 8. Employee accepts invite

**Web (password):**

| | |
|--|--|
| **Expected** | Employee active with password; can use web cabinet |
| **API** | `POST /api/v1/auth/invite/preview`, `POST /api/v1/auth/invite/accept` |
| **UI** | `/invite#<token>` |
| **DB** | `status=active`, `password_hash` set, invite consumed |
| **Security** | Rate-limited. Used/expired/wrong-purpose tokens fail closed. Role comes from invite row, not client input |

**Telegram (preferred for employees):**

| | |
|--|--|
| **Expected** | `/start <token>` binds Telegram and activates the employee (no password) |
| **API** | Bot → `POST /api/v1/auth/bot/invite/accept` with `X-Bot-Service-Token` |
| **UI** | Telegram deep link |
| **DB** | `telegram_user_id` / username / chat_id set; `status=active`; invite consumed |
| **Security** | Service token compared with `secrets.compare_digest`. Tenant comes from the invite's employee row (`telegram_user_id` → Employee → `company_id`), not `BOT_COMPANY_ID`. Duplicate Telegram account rejected. Rebinding another Telegram to an already-linked profile rejected. HR/Admin invite tokens rejected on this endpoint. Archived employees rejected |

---

## 9. Telegram `/start` (already bound)

| | |
|--|--|
| **Expected** | Greeting + menu (`Мой онбординг`) |
| **API** | Bot → `POST /api/v1/auth/bot/telegram` then tenant APIs with Bearer JWT |
| **UI** | Telegram bot |
| **DB** | `refresh_sessions` for the employee; no invite changes |
| **Security** | Invited (not yet accepted) → 403. Archived → 403. Unknown Telegram identity → 404/403. Missing/wrong service token → 401. Empty service token fail-closed. `BOT_COMPANY_ID` is not an identity scope |

---

## 10. Create onboarding program

| | |
|--|--|
| **Expected** | Draft program in the HR company |
| **API** | `POST /api/v1/programs` |
| **UI** | `/hr/onboarding/new` (Admin: `/company/onboarding/new`) |
| **DB** | `onboarding_programs` row; program limit enforced (starter=3) |
| **Security** | HR/Admin same company. Super Admin tokens cannot hit tenant program APIs |

---

## 11. Add step

| | |
|--|--|
| **Expected** | At least one step (content/task/quiz/ack) |
| **API** | `POST /api/v1/programs/{program_id}/steps` |
| **UI** | Program detail / steps editor |
| **DB** | `steps` row with `company_id` of the program |
| **Security** | Cross-company program UUID → 404. Payload size limited |

---

## 12. Publish

| | |
|--|--|
| **Expected** | Program status active; assignable |
| **API** | `POST /api/v1/programs/{program_id}/publish` |
| **UI** | Publish on program detail |
| **DB** | Program marked published/active; rejected if zero steps |
| **Security** | Same-company HR/Admin only |

---

## 13. Assign employee

| | |
|--|--|
| **Expected** | Assignment + progress rows for each step |
| **API** | `POST /api/v1/assignments` `{employee_id, program_id}` |
| **UI** | `/hr/assignments/new` |
| **DB** | `assignments` + `progress` rows `status=pending` (or equivalent) |
| **Security** | Employee and program must belong to caller company. Cannot assign invited/archived employees. Duplicate assignment → 409 |

---

## 14. Employee opens Telegram and completes a step

| | |
|--|--|
| **Expected** | Bot shows assigned program; completing a step marks progress done |
| **API** | Bot login (step 9); list assignments; `POST /api/v1/progress/{progress_id}/complete` |
| **UI** | Telegram «Мой онбординг»; web `/employee/onboarding` is optional |
| **DB** | `progress.completed_at` set; assignment progress counters update |
| **Security** | Only the **assigned employee** can complete their progress (peer HR/Admin cannot complete for them via this endpoint). Cross-tenant progress id → 404 |

---

## 15. HR sees completed progress

| | |
|--|--|
| **Expected** | Assignment detail / dashboard shows the step completed |
| **API** | `GET /api/v1/assignments/{id}` (and nested progress) |
| **UI** | `/hr/assignments/:assignmentId` and HR dashboard |
| **DB** | Read-only; no extra writes |
| **Security** | HR sees only their company. Super Admin uses `/platform/...`, not tenant assignment APIs |

---

## Subscription / fail-closed (throughout)

Production tenants need a **current** subscription in `{trial, active}` with
`ends_at` null or in the future. Missing current row → **403** (fail-closed).
`blocked` / `expired` / `suspended` → 403. Creating employees/programs beyond
limits → 400. Super Admin platform APIs are not blocked by tenant entitlement.

---

## Abort conditions (do not continue the pilot)

- API published on `:8000` while `TRUST_PROXY_HEADERS=true`
- Frontend bound to `0.0.0.0` (use `docker-compose.prod.yml` only)
- `SEED_DEMO=true`
- `BOT_COMPANY_ID` set to the demo seed UUID (leave it empty in production)
- Invite emails claiming `email_sent` when SMTP failed
- Raw invite tokens in `docker compose logs`
