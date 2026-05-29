from dataclasses import dataclass

from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.database import SessionLocal


@dataclass(frozen=True)
class DependencyStatus:
    ok: bool
    error: str | None = None

    def as_dict(self) -> dict[str, str | bool | None]:
        return {"ok": self.ok, "error": self.error}


def check_database() -> DependencyStatus:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return DependencyStatus(ok=True)
    except SQLAlchemyError as exc:
        return DependencyStatus(ok=False, error=exc.__class__.__name__)


def check_redis() -> DependencyStatus:
    settings = get_settings()
    try:
        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        client.ping()
        return DependencyStatus(ok=True)
    except RedisError as exc:
        return DependencyStatus(ok=False, error=exc.__class__.__name__)


def readiness_status() -> tuple[bool, dict[str, DependencyStatus]]:
    dependencies = {
        "database": check_database(),
        "redis": check_redis(),
    }
    return all(status.ok for status in dependencies.values()), dependencies
