import re
from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.ai_constants import DEFAULT_TELEGRAM_CONVERSATION_TTL_SECONDS

# Documented / common insecure values — rejected in production even if long enough.
_WEAK_SECRET_KEYS = frozenset(
    {
        "change-me",
        "changeme",
        "secret",
        "password",
        "secret_key",
        "secretkey",
        "your-secret-key",
        "your_secret_key",
        "dev-secret",
        "dev-only-change-me-to-a-long-random-secret",
        "test",
        "testing",
        "example",
        "openssl rand -hex 32",
        "<generate-a-strong-random-secret>",
    }
)

_WEAK_SUPER_ADMIN_PASSWORDS = frozenset(
    {
        "change-me-super-admin",
        "change-me",
        "changeme",
        "admin",
        "admin123",
        "password",
        "password123",
        "superadmin",
        "super-admin",
        "super_admin",
        "superadmin123",
        "<set-a-strong-unique-password>",
    }
)

# Documented / common insecure Postgres passwords — rejected in production.
_WEAK_POSTGRES_PASSWORDS = frozenset(
    {
        "onboard",
        "postgres",
        "password",
        "password123",
        "admin",
        "admin123",
        "changeme",
        "change-me",
        "secret",
        "test",
        "testing",
        "example",
        "<generate-a-strong-random-password>",
        "<set-a-strong-unique-password>",
    }
)

_WEAK_BOT_SERVICE_TOKENS = frozenset(
    {
        "change-me",
        "changeme",
        "bot-token",
        "bot_service_token",
        "botservicetoken",
        "<generate-a-strong-bot-service-token>",
    }
)

_WEAK_REDIS_PASSWORDS = frozenset(
    {
        "redis",
        "password",
        "changeme",
        "change-me",
        "secret",
        "onboard",
        "<generate-a-strong-random-password>",
    }
)

_MIN_SECRET_KEY_LEN = 32
_MIN_SUPER_ADMIN_PASSWORD_LEN = 12
_MIN_POSTGRES_PASSWORD_LEN = 12
_MIN_BOT_SERVICE_TOKEN_LEN = 24
_MIN_REDIS_PASSWORD_LEN = 12
_PLACEHOLDER_RE = re.compile(r"^<[^>]+>$")
# scripts/seed_demo.py well-known tenant — must not be the production bot binding.
_DEMO_SEED_COMPANY_ID = "11111111-1111-4111-8111-111111111111"


def _is_missing_or_weak_secret(value: str, *, weak_values: frozenset[str], min_length: int) -> bool:
    """Return True when value is empty, too short, a known weak default, or a placeholder."""
    stripped = value.strip()
    if not stripped:
        return True
    if len(stripped) < min_length:
        return True
    lowered = stripped.lower()
    if lowered in weak_values:
        return True
    if _PLACEHOLDER_RE.match(stripped):
        return True
    return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "OnboardAI"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change-me"

    # Auth / JWT
    auth_password: str = "change-me-auth"
    # Shared AUTH_PASSWORD for users without password_hash (dev/demo only).
    # Forced off when APP_ENV=production.
    allow_shared_auth_password: bool = True
    jwt_algorithm: str = "HS256"
    # Exact iss/aud binding for access JWTs (F-09). Override in production if
    # multiple OnboardAI deployments share infrastructure.
    jwt_issuer: str = "onboard-ai"
    jwt_audience: str = "onboard-ai-api"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    # Password login rate limits (per client IP, fixed window)
    login_rate_limit: int = 10
    login_rate_window_seconds: int = 60
    # Invite preview / accept rate limits (per client IP, fixed window)
    invite_preview_rate_limit: int = 30
    invite_preview_rate_window_seconds: int = 60
    invite_accept_rate_limit: int = 10
    invite_accept_rate_window_seconds: int = 60
    # Refresh token rotation rate limits (per client IP, fixed window).
    # Higher than login: opaque tokens resist guessing; multi-tab browsers and
    # the Telegram bot (many users, one egress IP) refresh routinely.
    refresh_rate_limit: int = 120
    refresh_rate_window_seconds: int = 60

    # Platform Super Admin bootstrap (seeded on API start when set)
    super_admin_email: str = "superadmin@onboard.local"
    super_admin_password: str = "change-me-super-admin"
    super_admin_full_name: str = "Super Admin"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # When True, prefer X-Forwarded-For / X-Real-IP for client IP (rate limits).
    # Enable only behind a trusted reverse proxy that overwrites these headers,
    # and only when the API is not exposed directly to the public internet.
    trust_proxy_headers: bool = False

    bot_token: str = ""
    bot_webhook_url: str = ""
    bot_webhook_secret: str = ""
    bot_webhook_path: str = "/webhook"
    bot_webhook_host: str = "0.0.0.0"
    bot_webhook_port: int = 8081
    bot_company_id: str = ""
    bot_service_token: str = ""
    # Public Telegram bot username (without @) for employee invite deep links.
    telegram_bot_username: str = ""
    # Bot telegram-login rate limit (per client IP, fixed window)
    bot_login_rate_limit: int = 30
    bot_login_rate_window_seconds: int = 60
    api_base_url: str = "http://localhost:8000"

    # Invites & email
    invite_ttl_hours: int = 24
    invite_base_url: str = "http://localhost:3000"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "noreply@onboard.local"
    smtp_use_tls: bool = True

    # Dev default uses local credentials. Production requires a strong password
    # in the URL (see docker-compose.prod.yml + POSTGRES_PASSWORD).
    # SEC-R3: runtime must use onboard_app (non-owner, no BYPASSRLS).
    database_url: str = (
        "postgresql+asyncpg://onboard_app:onboard@localhost:5432/onboard_ai"
    )
    # Alembic / DDL role (onboard_owner, BYPASSRLS). Production must set explicitly.
    # When unset, alembic/env.py falls back to DATABASE_URL (local transition only).
    migration_database_url: str = (
        "postgresql+asyncpg://onboard_owner:onboard@localhost:5432/onboard_ai"
    )
    # Passwords used when Alembic creates onboard_owner / onboard_app (M2).
    # Defaults match local docker; production must set strong unique values.
    onboard_owner_password: str = "onboard"
    onboard_app_password: str = "onboard"
    # Dev default has no password. Production requires a password in the URL
    # (see docker-compose.prod.yml + REDIS_PASSWORD).
    redis_url: str = "redis://localhost:6379/0"

    # AI embeddings. Dev/CI default is FakeEmbeddingProvider (no network).
    # Production hosted default is OpenAI text-embedding-3-small (1536).
    # API keys belong in env only — never in the repository or in logs.
    ai_embedding_provider: str = "fake"
    ai_embedding_dimension: int = 1536
    ai_embedding_model: str = "text-embedding-3-small"
    ai_embedding_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("AI_EMBEDDING_API_KEY", "OPENAI_API_KEY"),
    )
    ai_embedding_timeout_seconds: float = 30.0
    # AI-9A LLM. Dev/CI default is FakeLLMProvider (no network).
    # Keys belong in env only — never in the repository or in logs.
    ai_llm_provider: str = "fake"
    ai_llm_model: str = "gpt-4o-mini"
    ai_llm_api_key: SecretStr = Field(
        default=SecretStr(""),
        validation_alias=AliasChoices("AI_LLM_API_KEY", "OPENAI_API_KEY"),
    )
    ai_llm_timeout_seconds: float = 30.0
    # AI-9B HTTP chat rate limit (per authenticated employee, fixed window).
    # 0 disables the limiter (tests). Not an authorization mechanism.
    ai_chat_rate_limit: int = 20
    ai_chat_rate_window_seconds: int = 60
    # AI-10A: bounded OpenAI retries and overall RAG chat budget.
    # Chat timeout must stay below the Telegram HTTP client timeout (30s).
    ai_provider_max_retries: int = 2
    ai_provider_retry_backoff_seconds: float = 0.2
    ai_provider_retry_max_backoff_seconds: float = 2.0
    ai_chat_timeout_seconds: float = 25.0
    # AI-11C: Redis TTL for the Telegram → conversation_id pointer.
    # Not conversation history; Postgres remains the source of truth.
    ai_telegram_conversation_ttl_seconds: int = DEFAULT_TELEGRAM_CONVERSATION_TTL_SECONDS

    @field_validator("ai_embedding_provider")
    @classmethod
    def _validate_embedding_provider(cls, value: str) -> str:
        from app.core.ai_constants import SUPPORTED_EMBEDDING_PROVIDERS

        normalized = value.strip().lower()
        if normalized not in SUPPORTED_EMBEDDING_PROVIDERS:
            raise ValueError(
                "AI_EMBEDDING_PROVIDER must be 'fake' or 'openai'"
            )
        return normalized

    @field_validator("ai_embedding_dimension")
    @classmethod
    def _validate_embedding_dimension(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("AI_EMBEDDING_DIMENSION must be an integer")
        if value < 1 or value > 4096:
            raise ValueError("AI_EMBEDDING_DIMENSION must be between 1 and 4096")
        return value

    @field_validator("ai_embedding_timeout_seconds")
    @classmethod
    def _validate_embedding_timeout(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("AI_EMBEDDING_TIMEOUT_SECONDS must be a number")
        if value <= 0 or value > 120:
            raise ValueError("AI_EMBEDDING_TIMEOUT_SECONDS must be between 0 and 120")
        return float(value)

    @field_validator("ai_llm_provider")
    @classmethod
    def _validate_llm_provider(cls, value: str) -> str:
        from app.core.ai_constants import SUPPORTED_LLM_PROVIDERS

        normalized = value.strip().lower()
        if normalized not in SUPPORTED_LLM_PROVIDERS:
            raise ValueError("AI_LLM_PROVIDER must be 'fake' or 'openai'")
        return normalized

    @field_validator("ai_llm_timeout_seconds")
    @classmethod
    def _validate_llm_timeout(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("AI_LLM_TIMEOUT_SECONDS must be a number")
        if value <= 0 or value > 120:
            raise ValueError("AI_LLM_TIMEOUT_SECONDS must be between 0 and 120")
        return float(value)

    @field_validator("ai_chat_rate_limit")
    @classmethod
    def _validate_ai_chat_rate_limit(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("AI_CHAT_RATE_LIMIT must be an integer")
        if value < 0:
            raise ValueError("AI_CHAT_RATE_LIMIT must be >= 0")
        return value

    @field_validator("ai_chat_rate_window_seconds")
    @classmethod
    def _validate_ai_chat_rate_window(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("AI_CHAT_RATE_WINDOW_SECONDS must be an integer")
        if value < 1 or value > 3600:
            raise ValueError("AI_CHAT_RATE_WINDOW_SECONDS must be between 1 and 3600")
        return value

    @field_validator("ai_provider_max_retries")
    @classmethod
    def _validate_ai_provider_max_retries(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("AI_PROVIDER_MAX_RETRIES must be an integer")
        if value < 0 or value > 5:
            raise ValueError("AI_PROVIDER_MAX_RETRIES must be between 0 and 5")
        return value

    @field_validator("ai_provider_retry_backoff_seconds")
    @classmethod
    def _validate_ai_provider_retry_backoff(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("AI_PROVIDER_RETRY_BACKOFF_SECONDS must be a number")
        if value < 0 or value > 10:
            raise ValueError("AI_PROVIDER_RETRY_BACKOFF_SECONDS must be between 0 and 10")
        return float(value)

    @field_validator("ai_provider_retry_max_backoff_seconds")
    @classmethod
    def _validate_ai_provider_retry_max_backoff(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("AI_PROVIDER_RETRY_MAX_BACKOFF_SECONDS must be a number")
        if value <= 0 or value > 30:
            raise ValueError(
                "AI_PROVIDER_RETRY_MAX_BACKOFF_SECONDS must be between 0 and 30"
            )
        return float(value)

    @field_validator("ai_chat_timeout_seconds")
    @classmethod
    def _validate_ai_chat_timeout(cls, value: float) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("AI_CHAT_TIMEOUT_SECONDS must be a number")
        if value <= 0 or value > 120:
            raise ValueError("AI_CHAT_TIMEOUT_SECONDS must be between 0 and 120")
        return float(value)

    @field_validator("ai_telegram_conversation_ttl_seconds")
    @classmethod
    def _validate_telegram_conversation_ttl(cls, value: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("AI_TELEGRAM_CONVERSATION_TTL_SECONDS must be an integer")
        if value < 60 or value > 30 * 24 * 3600:
            raise ValueError(
                "AI_TELEGRAM_CONVERSATION_TTL_SECONDS must be between 60 and 2592000"
            )
        return value

    @model_validator(mode="after")
    def _harden_runtime(self) -> "Settings":
        from app.core.ai_constants import (
            KB_CHUNK_VECTOR_DIMENSION,
            OPENAI_EMBEDDING_DIMENSION,
        )

        if self.ai_embedding_provider == "openai":
            if not self.ai_embedding_api_key.get_secret_value().strip():
                raise ValueError(
                    "AI_EMBEDDING_API_KEY (or OPENAI_API_KEY) is required when "
                    "AI_EMBEDDING_PROVIDER=openai"
                )
            if self.ai_embedding_dimension != OPENAI_EMBEDDING_DIMENSION:
                raise ValueError(
                    "AI_EMBEDDING_DIMENSION must be "
                    f"{OPENAI_EMBEDDING_DIMENSION} when AI_EMBEDDING_PROVIDER=openai"
                )
            if self.ai_embedding_dimension != KB_CHUNK_VECTOR_DIMENSION:
                raise ValueError(
                    "AI_EMBEDDING_DIMENSION must match the pgvector column width "
                    f"({KB_CHUNK_VECTOR_DIMENSION})"
                )
            if not self.ai_embedding_model.strip():
                raise ValueError("AI_EMBEDDING_MODEL must not be empty")

        if self.ai_llm_provider == "openai":
            if not self.ai_llm_api_key.get_secret_value().strip():
                raise ValueError(
                    "AI_LLM_API_KEY (or OPENAI_API_KEY) is required when "
                    "AI_LLM_PROVIDER=openai"
                )
            if not self.ai_llm_model.strip():
                raise ValueError("AI_LLM_MODEL must not be empty")

        # Bot service token must always be company-bound (all environments).
        if self.bot_service_token and not self.bot_company_id:
            raise ValueError(
                "BOT_COMPANY_ID is required whenever BOT_SERVICE_TOKEN is set"
            )

        if self.app_env.lower() != "production":
            return self

        # Shared MVP password must never work in production.
        object.__setattr__(self, "allow_shared_auth_password", False)

        if self.debug:
            raise ValueError("DEBUG must be false when APP_ENV=production")

        if _is_missing_or_weak_secret(
            self.secret_key,
            weak_values=_WEAK_SECRET_KEYS,
            min_length=_MIN_SECRET_KEY_LEN,
        ):
            raise ValueError(
                "SECRET_KEY is missing or too weak for APP_ENV=production "
                f"(use a unique random value, >= {_MIN_SECRET_KEY_LEN} chars; "
                "e.g. openssl rand -hex 32)"
            )

        if _is_missing_or_weak_secret(
            self.super_admin_password,
            weak_values=_WEAK_SUPER_ADMIN_PASSWORDS,
            min_length=_MIN_SUPER_ADMIN_PASSWORD_LEN,
        ):
            raise ValueError(
                "SUPER_ADMIN_PASSWORD is missing or too weak for APP_ENV=production "
                f"(use a unique strong password, >= {_MIN_SUPER_ADMIN_PASSWORD_LEN} chars)"
            )

        if self.bot_service_token and _is_missing_or_weak_secret(
            self.bot_service_token,
            weak_values=_WEAK_BOT_SERVICE_TOKENS,
            min_length=_MIN_BOT_SERVICE_TOKEN_LEN,
        ):
            raise ValueError(
                "BOT_SERVICE_TOKEN is missing or too weak for APP_ENV=production "
                f"(use a unique random value, >= {_MIN_BOT_SERVICE_TOKEN_LEN} chars)"
            )
        if self.bot_token.strip() and not self.bot_service_token.strip():
            raise ValueError(
                "BOT_SERVICE_TOKEN is required when BOT_TOKEN is set and "
                "APP_ENV=production"
            )
        if (
            self.bot_company_id.strip().lower() == _DEMO_SEED_COMPANY_ID
        ):
            raise ValueError(
                "BOT_COMPANY_ID must not use the demo seed company id when "
                "APP_ENV=production (set it to the real pilot tenant UUID)"
            )
        invite_base = self.invite_base_url.strip().lower()
        if not invite_base.startswith("https://"):
            raise ValueError(
                "INVITE_BASE_URL must use https:// when APP_ENV=production"
            )
        if _is_missing_or_weak_secret(
            self.onboard_app_password,
            weak_values=_WEAK_POSTGRES_PASSWORDS,
            min_length=_MIN_POSTGRES_PASSWORD_LEN,
        ):
            raise ValueError(
                "ONBOARD_APP_PASSWORD is missing or too weak for APP_ENV=production "
                f"(use a unique strong value, >= {_MIN_POSTGRES_PASSWORD_LEN} chars)"
            )
        if _is_missing_or_weak_secret(
            self.onboard_owner_password,
            weak_values=_WEAK_POSTGRES_PASSWORDS,
            min_length=_MIN_POSTGRES_PASSWORD_LEN,
        ):
            raise ValueError(
                "ONBOARD_OWNER_PASSWORD is missing or too weak for APP_ENV=production "
                f"(use a unique strong value, >= {_MIN_POSTGRES_PASSWORD_LEN} chars)"
            )
        redis_password = _redis_url_password(self.redis_url)
        if redis_password is None or _is_missing_or_weak_secret(
            redis_password,
            weak_values=_WEAK_REDIS_PASSWORDS,
            min_length=_MIN_REDIS_PASSWORD_LEN,
        ):
            raise ValueError(
                "REDIS_URL must include a strong non-empty password when "
                "APP_ENV=production "
                f"(>= {_MIN_REDIS_PASSWORD_LEN} chars; "
                "example: redis://:${REDIS_PASSWORD}@redis:6379/0)"
            )
        db_password = _database_url_password(self.database_url)
        if db_password is None or _is_missing_or_weak_secret(
            db_password,
            weak_values=_WEAK_POSTGRES_PASSWORDS,
            min_length=_MIN_POSTGRES_PASSWORD_LEN,
        ):
            raise ValueError(
                "DATABASE_URL password is missing or too weak for APP_ENV=production "
                f"(set POSTGRES_PASSWORD / ONBOARD_APP_PASSWORD to a unique strong value, "
                f">= {_MIN_POSTGRES_PASSWORD_LEN} chars; "
                "do not use the development default 'onboard')"
            )
        mig_url = self.migration_database_url.strip()
        if not mig_url:
            raise ValueError(
                "MIGRATION_DATABASE_URL is required when APP_ENV=production "
                "(must use onboard_owner, separate from runtime DATABASE_URL)"
            )
        mig_password = _database_url_password(mig_url)
        if mig_password is None or _is_missing_or_weak_secret(
            mig_password,
            weak_values=_WEAK_POSTGRES_PASSWORDS,
            min_length=_MIN_POSTGRES_PASSWORD_LEN,
        ):
            raise ValueError(
                "MIGRATION_DATABASE_URL password is missing or too weak for "
                "APP_ENV=production (use onboard_owner with a strong password)"
            )
        if _database_url_username(self.database_url) != "onboard_app":
            raise ValueError(
                "DATABASE_URL must use the onboard_app role when APP_ENV=production "
                "(runtime must not connect as table owner / migrator)"
            )
        if _database_url_username(mig_url) != "onboard_owner":
            raise ValueError(
                "MIGRATION_DATABASE_URL must use the onboard_owner role when "
                "APP_ENV=production"
            )
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


def _redis_url_password(redis_url: str) -> str | None:
    """Extract the password from a Redis URL, or None if absent/empty."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        return None
    if parsed.password is None:
        return None
    password = unquote(parsed.password)
    if not password:
        return None
    return password


def _redis_url_has_password(redis_url: str) -> bool:
    """Return True when the Redis URL embeds a non-empty password."""
    return _redis_url_password(redis_url) is not None


def _database_url_password(database_url: str) -> str | None:
    """Extract the password from a SQLAlchemy/asyncpg DATABASE_URL, or None if absent."""
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    if not parsed.scheme.startswith("postgresql"):
        return None
    if parsed.password is None:
        return None
    return unquote(parsed.password)


def _database_url_username(database_url: str) -> str | None:
    """Extract the username from a SQLAlchemy/asyncpg DATABASE_URL.

    Returns None when the scheme is not PostgreSQL, the username is missing,
    or the username is empty after URL-decoding. Used for exact role checks
    (never substring matching).
    """
    from urllib.parse import unquote, urlparse

    try:
        parsed = urlparse(database_url)
    except Exception:
        return None
    if not parsed.scheme.startswith("postgresql"):
        return None
    if parsed.username is None:
        return None
    username = unquote(parsed.username)
    if not username:
        return None
    return username


@lru_cache
def get_settings() -> Settings:
    return Settings()
