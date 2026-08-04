from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "OnboardAI"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change-me"

    # Auth / JWT
    auth_password: str = "change-me-auth"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    api_host: str = "0.0.0.0"
    api_port: int = 8000

    bot_token: str = ""
    bot_webhook_url: str = ""
    bot_webhook_secret: str = ""
    bot_webhook_path: str = "/webhook"
    bot_webhook_host: str = "0.0.0.0"
    bot_webhook_port: int = 8081
    bot_company_id: str = ""
    bot_service_token: str = ""
    # Bot telegram-login rate limit (per client IP, fixed window)
    bot_login_rate_limit: int = 30
    bot_login_rate_window_seconds: int = 60
    api_base_url: str = "http://localhost:8000"

    database_url: str = "postgresql+asyncpg://onboard:onboard@localhost:5432/onboard_ai"
    redis_url: str = "redis://localhost:6379/0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
