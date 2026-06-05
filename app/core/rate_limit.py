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
    _LUA_SCRIPT = """
    local current = redis.call('INCR', KEYS[1])
    if current == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end
    local ttl = redis.call('TTL', KEYS[1])
    return {current, ttl}
    """

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
            current, ttl = [
                int(value)
                for value in self.redis.eval(
                    self._LUA_SCRIPT,
                    1,
                    redis_key,
                    int(window_seconds),
                )
            ]
        except RedisError as exc:
            raise RateLimitUnavailable("Redis rate limiter unavailable") from exc

        retry_after = ttl if ttl > 0 else window_seconds
        return RateLimitDecision(
            allowed=current <= max(1, limit),
            current=current,
            retry_after_seconds=retry_after,
        )
