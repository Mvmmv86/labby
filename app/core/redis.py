from collections.abc import Generator

from redis import Redis

from app.core.config import get_settings


def make_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> Generator[Redis, None, None]:
    client = make_redis_client()
    try:
        yield client
    finally:
        client.close()
