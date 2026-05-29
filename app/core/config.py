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
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(default=DEFAULT_JWT_SECRET, min_length=16)
    jwt_issuer: str = "labby-api"
    jwt_audience: str = "labby-app"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
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
