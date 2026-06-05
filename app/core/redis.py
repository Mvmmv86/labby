from collections.abc import Generator
from functools import lru_cache

from redis import Redis

from app.core.config import get_settings


def make_redis_client() -> Redis:
    settings = get_settings()
    return _redis_client_from_url(settings.redis_url)


@lru_cache
def _redis_client_from_url(redis_url: str) -> Redis:
    return Redis.from_url(redis_url, decode_responses=True)


def get_redis() -> Generator[Redis, None, None]:
    client = make_redis_client()
    yield client
