from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_JWT_SECRET = "change-me-in-production"
PROTECTED_ENVIRONMENTS = {"production", "prod", "staging"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LABBY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    database_url: str = "postgresql+psycopg://labby:labby@localhost:5432/labby"
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: int = 30
    database_pool_recycle_seconds: int = 1800
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(default=DEFAULT_JWT_SECRET, min_length=16)
    jwt_issuer: str = "labby-api"
    jwt_audience: str = "labby-app"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    app_base_url: str = "https://app.labby.com.br"
    email_from: str = "Labby <convites@labby.com.br>"
    resend_api_key: str | None = None
    resend_timeout_seconds: float = 10.0
    x_api_provider: str = "twitterapi_io"
    x_api_key: str | None = None
    x_api_base_url: str | None = None
    x_api_timeout_seconds: float = 30.0
    twitterapi_io_key: str | None = None
    ai_provider: str = "fallback"
    ai_api_key: str | None = None
    ai_model_default: str = "gpt-4o-mini"
    ai_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = 30.0
    ai_input_cost_per_million_tokens: float = 0.0
    ai_output_cost_per_million_tokens: float = 0.0
    job_running_timeout_seconds: int = 900
    job_reaper_batch_size: int = 50
    social_news_capture_lookback_hours: int = 24
    social_news_max_source_requests_per_run: int = 10
    social_news_posts_per_source: int = 20
    social_news_capture_limit: int = 30
    social_news_rank_limit: int = 5
    allowed_origins: str = (
        "http://localhost:3000,http://localhost:3001,https://app.labby.com.br"
    )
    docs_enabled: bool = True
    timezone: str = "America/Sao_Paulo"

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_protected_environment(self) -> Self:
        environment = self.environment.lower()
        if environment not in PROTECTED_ENVIRONMENTS:
            return self

        if self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32:
            raise ValueError(
                "LABBY_JWT_SECRET must be changed and have at least 32 characters "
                "outside development."
            )

        if "localhost" in self.database_url or "localhost" in self.redis_url:
            raise ValueError(
                "LABBY_DATABASE_URL and LABBY_REDIS_URL must point to managed services "
                "outside development."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
