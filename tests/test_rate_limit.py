from redis.exceptions import RedisError

import app.core.redis as redis_module
from app.core.rate_limit import RateLimitUnavailable, RedisFixedWindowRateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expirations: dict[str, int] = {}
        self.eval_calls: list[tuple[str, int, str, int]] = []

    def eval(self, script: str, numkeys: int, key: str, window_seconds: int) -> list[int]:
        self.eval_calls.append((script, numkeys, key, window_seconds))
        self.values[key] = self.values.get(key, 0) + 1
        if self.values[key] == 1:
            self.expirations[key] = window_seconds
        return [self.values[key], self.expirations.get(key, -1)]


class FailingRedis(FakeRedis):
    def eval(self, script: str, numkeys: int, key: str, window_seconds: int) -> list[int]:
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
    assert len(redis.eval_calls) == 3
    assert redis.eval_calls[0][1:] == (1, "labby:rate-limit:widget:1", 60)


def test_redis_fixed_window_rate_limiter_fails_closed_when_unavailable() -> None:
    limiter = RedisFixedWindowRateLimiter(FailingRedis())

    try:
        limiter.check(key="widget:1", limit=2)
    except RateLimitUnavailable as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("expected RateLimitUnavailable")


def test_make_redis_client_reuses_process_singleton(monkeypatch) -> None:
    clients = []

    def fake_from_url(redis_url: str, *, decode_responses: bool):
        client = {"url": redis_url, "decode_responses": decode_responses, "index": len(clients)}
        clients.append(client)
        return client

    redis_module._redis_client_from_url.cache_clear()
    monkeypatch.setattr(redis_module.Redis, "from_url", fake_from_url)

    first = redis_module.make_redis_client()
    second = redis_module.make_redis_client()

    assert first is second
    assert len(clients) == 1
    assert clients[0]["decode_responses"] is True
    redis_module._redis_client_from_url.cache_clear()
