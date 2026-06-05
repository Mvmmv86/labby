from dataclasses import dataclass
from typing import Protocol

from redis import Redis
from redis.exceptions import RedisError

from app.core.redis import make_redis_client


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    current: int
    retry_after_seconds: int


class RateLimitUnavailable(RuntimeError):
    pass


class PublicRateLimiter(Protocol):
    def check(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitDecision:
        ...


class RedisFixedWindowRateLimiter:
    def __init__(self, redis_client: Redis | None = None) -> None:
        self.redis = redis_client or make_redis_client()

    def check(
        self,
        *,
        key: str,
        limit: int,
        window_seconds: int = 60,
    ) -> RateLimitDecision:
        redis_key = f"labby:rate-limit:{key}"
        try:
            current = int(self.redis.incr(redis_key))
            if current == 1:
                self.redis.expire(redis_key, window_seconds)
            ttl = int(self.redis.ttl(redis_key))
        except RedisError as exc:
            raise RateLimitUnavailable("Redis rate limiter unavailable") from exc

        retry_after = ttl if ttl > 0 else window_seconds
        return RateLimitDecision(
            allowed=current <= max(1, limit),
            current=current,
            retry_after_seconds=retry_after,
        )
