from redis.exceptions import RedisError

from app.core.rate_limit import RateLimitUnavailable, RedisFixedWindowRateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds

    def ttl(self, key: str) -> int:
        return self.expirations.get(key, -1)


class FailingRedis(FakeRedis):
    def incr(self, key: str) -> int:
        raise RedisError("down")


def test_redis_fixed_window_rate_limiter_counts_and_sets_ttl() -> None:
    redis = FakeRedis()
    limiter = RedisFixedWindowRateLimiter(redis)

    first = limiter.check(key="widget:1", limit=2, window_seconds=60)
    second = limiter.check(key="widget:1", limit=2, window_seconds=60)
    third = limiter.check(key="widget:1", limit=2, window_seconds=60)

    assert first.allowed is True
    assert second.allowed is True
    assert third.allowed is False
    assert third.current == 3
    assert redis.expirations["labby:rate-limit:widget:1"] == 60


def test_redis_fixed_window_rate_limiter_fails_closed_when_unavailable() -> None:
    limiter = RedisFixedWindowRateLimiter(FailingRedis())

    try:
        limiter.check(key="widget:1", limit=2)
    except RateLimitUnavailable as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("expected RateLimitUnavailable")
