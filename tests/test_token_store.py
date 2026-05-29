import pytest

from app.domains.identity.token_store import (
    PasswordResetStore,
    RefreshTokenReuseError,
    RefreshTokenStore,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def pipeline(self):
        return FakePipeline(self)

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class FakePipeline:
    def __init__(self, redis: FakeRedis) -> None:
        self.redis = redis
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.reset()

    def watch(self, *keys: str) -> None:
        return None

    def unwatch(self) -> None:
        return None

    def get(self, key: str) -> str | None:
        return self.redis.get(key)

    def multi(self) -> None:
        return None

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.commands.append((key, ttl, value))

    def execute(self) -> None:
        for key, ttl, value in self.commands:
            self.redis.setex(key, ttl, value)
        self.commands.clear()

    def reset(self) -> None:
        self.commands.clear()


def test_refresh_token_rotation_rejects_reuse() -> None:
    redis = FakeRedis()
    store = RefreshTokenStore(redis, ttl_seconds=3600)

    refresh_token = store.issue(user_id="user-1", membership_id="membership-1")
    record, next_token = store.rotate(refresh_token)

    assert record.user_id == "user-1"
    assert next_token != refresh_token
    with pytest.raises(RefreshTokenReuseError):
        store.rotate(refresh_token)
    with pytest.raises(RefreshTokenReuseError):
        store.rotate(next_token)


def test_password_reset_token_is_single_use() -> None:
    redis = FakeRedis()
    store = PasswordResetStore(redis, ttl_seconds=3600)

    token = store.issue(user_id="user-1")
    first = store.consume(token)
    second = store.consume(token)

    assert first is not None
    assert first.user_id == "user-1"
    assert second is None
