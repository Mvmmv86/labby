import pytest

from app.domains.identity.token_store import (
    PasswordResetStore,
    RefreshTokenReuseError,
    RefreshTokenStore,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.sets: dict[str, set[str]] = {}

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
        self.sets.pop(key, None)

    def sadd(self, key: str, value: str) -> None:
        self.sets.setdefault(key, set()).add(value)

    def smembers(self, key: str) -> set[str]:
        return self.sets.get(key, set())

    def expire(self, key: str, ttl: int) -> None:
        return None


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

    def sadd(self, key: str, value: str) -> None:
        self.commands.append(("sadd", key, value))

    def expire(self, key: str, ttl: int) -> None:
        self.commands.append(("expire", key, ttl))

    def delete(self, key: str) -> None:
        self.commands.append(("delete", key, None))

    def execute(self) -> None:
        for command in self.commands:
            if command[0] == "sadd":
                _, key, value = command
                self.redis.sadd(key, value)
            elif command[0] == "expire":
                continue
            elif command[0] == "delete":
                _, key, _ = command
                self.redis.delete(key)
            else:
                key, ttl, value = command
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


def test_refresh_token_revoke_user_revokes_all_known_families() -> None:
    redis = FakeRedis()
    store = RefreshTokenStore(redis, ttl_seconds=3600)

    first = store.issue(user_id="user-1", membership_id="membership-1")
    second = store.issue(user_id="user-1", membership_id="membership-2")

    store.revoke_user("user-1")

    with pytest.raises(RefreshTokenReuseError):
        store.rotate(first)
    with pytest.raises(RefreshTokenReuseError):
        store.rotate(second)


def test_password_reset_token_is_single_use() -> None:
    redis = FakeRedis()
    store = PasswordResetStore(redis, ttl_seconds=3600)

    token = store.issue(user_id="user-1")
    first = store.consume(token)
    second = store.consume(token)

    assert first is not None
    assert first.user_id == "user-1"
    assert second is None
