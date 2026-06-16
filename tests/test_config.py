import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_JWT_SECRET, Settings


def test_development_allows_local_defaults() -> None:
    settings = Settings()
    assert settings.environment == "development"
    assert settings.jwt_secret == DEFAULT_JWT_SECRET


def test_production_rejects_default_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="LABBY_JWT_SECRET"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://labby:secret@db.example.com:5432/labby",
            redis_url="redis://redis.example.com:6379/0",
            jwt_secret=DEFAULT_JWT_SECRET,
        )


def test_staging_rejects_localhost_dependencies() -> None:
    with pytest.raises(ValidationError, match="LABBY_DATABASE_URL"):
        Settings(
            environment="staging",
            database_url="postgresql+psycopg://labby:labby@localhost:5432/labby",
            redis_url="redis://localhost:6379/0",
            jwt_secret="x" * 32,
        )


def test_staging_requires_redis_public_rate_limit_backend() -> None:
    with pytest.raises(ValidationError, match="LABBY_PUBLIC_RATE_LIMIT_BACKEND"):
        Settings(
            environment="staging",
            database_url="postgresql+psycopg://labby:secret@db.example.com:5432/labby",
            redis_url="redis://redis.example.com:6379/0",
            jwt_secret="x" * 32,
            public_rate_limit_backend="database",
        )


def test_staging_accepts_redis_public_rate_limit_backend() -> None:
    settings = Settings(
        environment="staging",
        database_url="postgresql+psycopg://labby:secret@db.example.com:5432/labby",
        redis_url="redis://redis.example.com:6379/0",
        jwt_secret="x" * 32,
        public_rate_limit_backend="redis",
    )

    assert settings.public_rate_limit_backend == "redis"


def test_apify_run_budget_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(apify_max_total_charge_usd=0)
