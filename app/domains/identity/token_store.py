import json
import secrets
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from redis import Redis
from redis.exceptions import WatchError

from app.core.security import hash_token, make_opaque_token


@dataclass(frozen=True)
class RefreshTokenRecord:
    user_id: str
    membership_id: str
    family_id: str
    status: str
    expires_at: str


class RefreshTokenReuseError(Exception):
    pass


class RefreshTokenNotFoundError(Exception):
    pass


class RefreshTokenStore:
    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    def issue(self, *, user_id: str, membership_id: str, family_id: str | None = None) -> str:
        token = make_opaque_token()
        family = family_id or str(uuid.uuid4())
        expires_at = (datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)).isoformat()
        record = RefreshTokenRecord(
            user_id=user_id,
            membership_id=membership_id,
            family_id=family,
            status="active",
            expires_at=expires_at,
        )
        self.redis.setex(self._token_key(token), self.ttl_seconds, json.dumps(asdict(record)))
        self.redis.setex(self._family_key(family), self.ttl_seconds, "active")
        return token

    def rotate(self, token: str) -> tuple[RefreshTokenRecord, str]:
        token_key = self._token_key(token)
        with self.redis.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(token_key)
                    raw_record = pipe.get(token_key)
                    if not raw_record:
                        pipe.unwatch()
                        raise RefreshTokenNotFoundError("Refresh token nao encontrado")

                    record = RefreshTokenRecord(**json.loads(raw_record))
                    family_key = self._family_key(record.family_id)
                    pipe.watch(family_key)
                    family_status = pipe.get(family_key)

                    if family_status == "revoked":
                        pipe.unwatch()
                        raise RefreshTokenReuseError("Familia de refresh token revogada")

                    if record.status != "active":
                        pipe.unwatch()
                        self.revoke_family(record.family_id)
                        raise RefreshTokenReuseError("Refresh token reutilizado")

                    rotated = RefreshTokenRecord(
                        user_id=record.user_id,
                        membership_id=record.membership_id,
                        family_id=record.family_id,
                        status="rotated",
                        expires_at=record.expires_at,
                    )
                    new_token = make_opaque_token()
                    active = RefreshTokenRecord(
                        user_id=record.user_id,
                        membership_id=record.membership_id,
                        family_id=record.family_id,
                        status="active",
                        expires_at=(
                            datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)
                        ).isoformat(),
                    )

                    pipe.multi()
                    pipe.setex(token_key, self.ttl_seconds, json.dumps(asdict(rotated)))
                    pipe.setex(
                        self._token_key(new_token),
                        self.ttl_seconds,
                        json.dumps(asdict(active)),
                    )
                    pipe.setex(family_key, self.ttl_seconds, "active")
                    pipe.execute()
                    return record, new_token
                except WatchError:
                    pipe.reset()

    def get(self, token: str) -> RefreshTokenRecord:
        raw = self.redis.get(self._token_key(token))
        if not raw:
            raise RefreshTokenNotFoundError("Refresh token nao encontrado")
        return RefreshTokenRecord(**json.loads(raw))

    def revoke(self, token: str) -> None:
        try:
            record = self.get(token)
        except RefreshTokenNotFoundError:
            return
        revoked = RefreshTokenRecord(
            user_id=record.user_id,
            membership_id=record.membership_id,
            family_id=record.family_id,
            status="revoked",
            expires_at=record.expires_at,
        )
        self.redis.setex(self._token_key(token), self.ttl_seconds, json.dumps(asdict(revoked)))

    def revoke_family(self, family_id: str) -> None:
        self.redis.setex(self._family_key(family_id), self.ttl_seconds, "revoked")

    @staticmethod
    def _token_key(token: str) -> str:
        return f"refresh:{hash_token(token)}"

    @staticmethod
    def _family_key(family_id: str) -> str:
        return f"refresh-family:{family_id}"


@dataclass(frozen=True)
class PasswordResetRecord:
    user_id: str
    expires_at: str


class PasswordResetStore:
    def __init__(self, redis: Redis, ttl_seconds: int = 60 * 60) -> None:
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    def issue(self, *, user_id: str) -> str:
        token = make_opaque_token()
        record = PasswordResetRecord(
            user_id=user_id,
            expires_at=(datetime.now(UTC) + timedelta(seconds=self.ttl_seconds)).isoformat(),
        )
        self.redis.setex(self._token_key(token), self.ttl_seconds, json.dumps(asdict(record)))
        return token

    def consume(self, token: str) -> PasswordResetRecord | None:
        key = self._token_key(token)
        raw = self.redis.getdel(key)
        if not raw:
            return None
        return PasswordResetRecord(**json.loads(raw))

    @staticmethod
    def _token_key(token: str) -> str:
        return f"password-reset:{hash_token(token)}"


def make_jti() -> str:
    return secrets.token_hex(16)
