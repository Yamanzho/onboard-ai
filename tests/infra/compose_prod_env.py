"""Shared env for docker compose -f docker-compose.prod.yml config tests.

Deterministic values — not production credentials. BOT_COMPANY_ID must not be
the demo seed UUID (rejected by Settings when APP_ENV=production).
"""

COMPOSE_PROD_SECRETS = {
    "REDIS_PASSWORD": "compose-test-redis-password-not-a-secret",
    "SECRET_KEY": "compose-test-hmac-secret-key-32chars-min!",
    "SUPER_ADMIN_PASSWORD": "compose-test-super-admin-ok",
    "POSTGRES_PASSWORD": "compose-test-postgres-password-ok",
    "ONBOARD_OWNER_PASSWORD": "compose-test-owner-password-ok",
    "ONBOARD_APP_PASSWORD": "compose-test-app-password-ok",
    "BOT_SERVICE_TOKEN": "compose-test-bot-service-token-32c",
    "BOT_COMPANY_ID": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "INVITE_BASE_URL": "https://onboardai.example.test",
}
