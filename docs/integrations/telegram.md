# Telegram integration

OnboardAI uses **one shared Telegram bot** for the entire SaaS. The bot is
shared. Tenant data is not.

## Identity

```
Telegram from_user.id
    → POST /api/v1/auth/bot/telegram
    → Employee (bound telegram_user_id, status=active)
    → employee.company_id
    → tenant context / JWT / RLS
```

The only trusted Telegram identity is `message.from_user.id`.

The Telegram user cannot select `company_id`, `tenant_id`, `employee_id`,
`role`, or permissions. Request `company_id` on bot endpoints is ignored.

## Binding

Real binding is `/start <invite_token>`:

1. HR creates an invited employee (Web `telegram_user_id` is informational).
2. Employee opens the Telegram deep link.
3. Bot calls `POST /api/v1/auth/bot/invite/accept` with the invite token and
   `from_user.id` / `chat.id` / username.
4. Employee becomes `active`, invite is consumed.

Web PATCH of `telegram_user_id` does **not** activate the employee and is not
an authentication shortcut.

`/start` without a valid token does not create a binding.

## Status gates

| Telegram identity | Bot login |
|-------------------|-----------|
| Unknown id | 404 — not registered |
| Invited | 403 — accept the invite first |
| Archived | 403 |
| Active | 200 — JWT for `employee.company_id` |

## Service-token trust boundary

The bot process authenticates to the API with `X-Bot-Service-Token`
(`BOT_SERVICE_TOKEN`). That token is **not** a tenant selector.

Employee JWTs are issued by the API and used as `Authorization: Bearer` on
subsequent REST calls. Telegram clients never carry raw JWTs in chat text.

## Tenant isolation

After login, every cabinet and AI call uses the employee JWT. Downstream
services call `enter_tenant(employee.company_id)`. Company A cannot read
Company B companies, employees, knowledge, assignments, or conversations.

Partial unique index `uq_employees_active_telegram_user_id` enforces:
one real Telegram user id → at most one **active** employee globally.
Invited/archived rows are excluded so placeholder Web ids do not collide.

If that index cannot be applied, the database still contains duplicate
**active** `telegram_user_id` values. Do not delete them automatically.
Resolve them, then migrate. Login fail-closes on ambiguous active matches.

This release revision `a7b8c9d0e1f2` revises production head `c8d9e0f1a2b3`.

Inspect before `alembic upgrade head`:

```sql
SELECT telegram_user_id, count(*) AS active_rows,
       count(DISTINCT company_id) AS companies
FROM employees
WHERE status = 'active'
GROUP BY telegram_user_id
HAVING count(*) > 1;
```

A local leftover from golden-path tests used `telegram_user_id = 9200000001`
across many “Pilot Tenant” companies. That is test residue, not a reason to
delete production rows. Production must be inspected with the same query.

## BOT_COMPANY_ID

Optional demo / default / ops metadata.

It is **not** used for shared-bot employee identity lookup.

Production Compose may still interpolate the variable. If it is set when
`APP_ENV=production`, it must not be the demo seed UUID
`11111111-1111-4111-8111-111111111111`.

## Debug

`BOT_IDENTITY_DEBUG=true` logs only:

- handler
- telegram_user_id
- telegram_chat_id
- employee_id
- company_id
- result
- HTTP status

Never logs bot token, service token, JWT, invite token, API keys, or passwords.
Default is off.

## Production

Required for a live bot:

- `BOT_TOKEN`
- `BOT_SERVICE_TOKEN` (same value on API and bot)
- `API_BASE_URL` (Compose: `http://api:8000`)
- `TELEGRAM_BOT_USERNAME` (invite deep links)
- database + Redis as in [DEPLOYMENT.md](../../DEPLOYMENT.md)

Employees must accept a Telegram invite (`/start <token>`) before menu actions
and AI work.
