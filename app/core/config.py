from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    jwt_secret: str = Field(default="change-me-in-production", min_length=16)
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


@lru_cache
def get_settings() -> Settings:
    return Settings()

