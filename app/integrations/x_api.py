from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import httpx

from app.core.config import Settings

logger = logging.getLogger("labby.integrations.x_api")


@dataclass(frozen=True)
class XAuthor:
    id: str | None
    handle: str
    name: str | None = None
    bio: str | None = None
    verified: bool = False
    verified_type: str | None = None
    followers_count: int | None = None
    following_count: int | None = None
    tweet_count: int | None = None
    created_at: datetime | None = None
    profile_image_url: str | None = None


@dataclass(frozen=True)
class XPost:
    id: str
    url: str
    text: str
    author: XAuthor
    like_count: int = 0
    retweet_count: int = 0
    reply_count: int = 0
    quote_count: int = 0
    impression_count: int = 0
    created_at: datetime | None = None
    lang: str | None = None
    media_urls: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def metrics(self) -> dict[str, int]:
        return {
            "likes": self.like_count,
            "retweets": self.retweet_count,
            "replies": self.reply_count,
            "quotes": self.quote_count,
            "impressions": self.impression_count,
        }


@dataclass(frozen=True)
class XPaginatedPosts:
    posts: list[XPost]
    next_cursor: str | None = None
    has_next_page: bool = False
    cost_usd: float = 0.0


class XApiError(Exception):
    pass


class XApiConfigurationError(XApiError):
    pass


class XApiAuthError(XApiError):
    pass


class XApiRateLimitError(XApiError):
    def __init__(self, message: str, retry_after_seconds: float | None = None):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class XApiTemporaryError(XApiError):
    pass


class XApiPermanentError(XApiError):
    pass


class XApiClient(Protocol):
    async def search_top_engagement(
        self,
        query: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        min_likes: int = 0,
        min_reposts: int = 0,
        min_replies: int = 0,
        min_impressions: int = 0,
        limit: int = 20,
        cursor: str | None = None,
    ) -> XPaginatedPosts:
        ...

    async def fetch_post_by_id(self, post_id: str) -> XPost | None:
        ...


class TwitterApiIoAdapter:
    base_url = "https://api.twitterapi.io"
    search_path = "/twitter/tweet/advanced_search"
    tweets_path = "/twitter/tweets"
    cost_per_tweet_usd = 0.00015

    def __init__(
        self,
        *,
        api_key: str | None,
        timeout_seconds: float,
        base_url: str | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = (base_url or self.base_url).rstrip("/")
        if not self.api_key:
            raise XApiConfigurationError(
                "LABBY_TWITTERAPI_IO_KEY ou LABBY_X_API_KEY nao configurada"
            )

    async def search_top_engagement(
        self,
        query: str,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        min_likes: int = 0,
        min_reposts: int = 0,
        min_replies: int = 0,
        min_impressions: int = 0,
        limit: int = 20,
        cursor: str | None = None,
    ) -> XPaginatedPosts:
        data = await self._get(
            self.search_path,
            {
                "query": self._build_query(
                    query,
                    since=since,
                    until=until,
                    min_likes=min_likes,
                    min_reposts=min_reposts,
                    min_replies=min_replies,
                    min_impressions=min_impressions,
                ),
                "queryType": "Top",
                "cursor": cursor or "",
            },
        )
        posts = [self._parse_post(item) for item in data.get("tweets", [])]
        posts = [
            post
            for post in posts
            if post.like_count >= min_likes
            and post.retweet_count >= min_reposts
            and post.reply_count >= min_replies
            and post.impression_count >= min_impressions
        ][:limit]
        return XPaginatedPosts(
            posts=posts,
            next_cursor=data.get("next_cursor") or None,
            has_next_page=bool(data.get("has_next_page")),
            cost_usd=len(posts) * self.cost_per_tweet_usd,
        )

    async def fetch_post_by_id(self, post_id: str) -> XPost | None:
        data = await self._get(self.tweets_path, {"tweet_ids": post_id})
        tweets = data.get("tweets") or []
        return self._parse_post(tweets[0]) if tweets else None

    def _build_query(
        self,
        query: str,
        *,
        since: datetime | None,
        until: datetime | None,
        min_likes: int,
        min_reposts: int,
        min_replies: int,
        min_impressions: int,
    ) -> str:
        parts = [query.strip()]
        if since:
            parts.append(f"since_time:{self._unix_seconds(since)}")
        if until:
            parts.append(f"until_time:{self._unix_seconds(until)}")
        if min_likes:
            parts.append(f"min_faves:{min_likes}")
        if min_reposts:
            parts.append(f"min_retweets:{min_reposts}")
        if min_replies:
            parts.append(f"min_replies:{min_replies}")
        if min_impressions:
            parts.append(f"min_views:{min_impressions}")
        return " ".join(part for part in parts if part)

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(
                    f"{self.base_url}{path}",
                    headers={"X-API-Key": self.api_key},
                    params=params,
                )
        except httpx.TimeoutException as exc:
            raise XApiTemporaryError("Timeout ao chamar TwitterAPI.io") from exc
        except httpx.HTTPError as exc:
            raise XApiTemporaryError(f"Falha HTTP ao chamar TwitterAPI.io: {exc}") from exc

        if response.status_code in (401, 403):
            raise XApiAuthError("TwitterAPI.io rejeitou a credencial")
        if response.status_code == 429:
            raise XApiRateLimitError(
                "Rate limit TwitterAPI.io",
                retry_after_seconds=self._retry_after_seconds(response),
            )
        if response.status_code >= 500:
            raise XApiTemporaryError(f"TwitterAPI.io indisponivel ({response.status_code})")
        if response.status_code >= 400:
            raise XApiPermanentError(
                f"TwitterAPI.io retornou erro {response.status_code}: {response.text[:300]}"
            )

        data = response.json()
        if data.get("status") == "error":
            message = data.get("msg") or data.get("message") or "erro desconhecido"
            raise XApiPermanentError(f"TwitterAPI.io status=error: {message}")
        return data

    def _parse_post(self, item: dict[str, Any]) -> XPost:
        author = item.get("author") or {}
        handle = (author.get("userName") or item.get("userName") or "").lstrip("@")
        post_id = str(item.get("id") or "")
        return XPost(
            id=post_id,
            url=item.get("url")
            or (f"https://x.com/{handle}/status/{post_id}" if handle and post_id else ""),
            text=item.get("text") or "",
            author=XAuthor(
                id=self._optional_str(author.get("id")),
                handle=handle,
                name=author.get("name"),
                bio=author.get("description"),
                verified=bool(author.get("isBlueVerified") or author.get("verified")),
                verified_type=author.get("verifiedType"),
                followers_count=self._to_int(author.get("followers")),
                following_count=self._to_int(author.get("following")),
                tweet_count=self._to_int(author.get("statusesCount")),
                created_at=self._parse_datetime(author.get("createdAt")),
                profile_image_url=author.get("profilePicture"),
            ),
            like_count=self._to_int(item.get("likeCount")),
            retweet_count=self._to_int(item.get("retweetCount")),
            reply_count=self._to_int(item.get("replyCount")),
            quote_count=self._to_int(item.get("quoteCount")),
            impression_count=self._to_int(item.get("viewCount")),
            created_at=self._parse_datetime(item.get("createdAt")),
            lang=item.get("lang"),
            media_urls=self._extract_media_urls(item),
            raw=item,
        )

    def _extract_media_urls(self, item: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        containers = [
            item.get("media"),
            (item.get("entities") or {}).get("media"),
            (item.get("extendedEntities") or {}).get("media"),
            (item.get("extended_entities") or {}).get("media"),
        ]
        for container in containers:
            if not container:
                continue
            values = container if isinstance(container, list) else [container]
            for media in values:
                if not isinstance(media, dict):
                    continue
                url = (
                    media.get("media_url_https")
                    or media.get("media_url")
                    or media.get("url")
                    or media.get("preview_image_url")
                )
                if url and url not in urls:
                    urls.append(url)
        return urls

    def _parse_datetime(self, value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                logger.debug("twitterapi_io_unparsed_datetime value=%s", value)
                return None
        if parsed.tzinfo:
            return parsed.astimezone(UTC).replace(tzinfo=None)
        return parsed

    def _unix_seconds(self, value: datetime) -> int:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp())

    def _retry_after_seconds(self, response: httpx.Response) -> float | None:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                except (TypeError, ValueError):
                    retry_at = None
                if retry_at:
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())

        reset_at = response.headers.get("x-rate-limit-reset")
        if reset_at:
            try:
                return max(0.0, float(reset_at) - datetime.now(UTC).timestamp())
            except ValueError:
                return None
        return None

    def _to_int(self, value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _optional_str(self, value: Any) -> str | None:
        return None if value is None else str(value)


def make_x_client(settings: Settings) -> XApiClient:
    provider = (settings.x_api_provider or "twitterapi_io").strip().lower()
    if provider == "twitterapi_io":
        return TwitterApiIoAdapter(
            api_key=settings.twitterapi_io_key or settings.x_api_key,
            timeout_seconds=settings.x_api_timeout_seconds,
            base_url=settings.x_api_base_url,
        )
    if provider == "official":
        raise XApiConfigurationError("Provider oficial do X ainda nao implementado")
    raise XApiConfigurationError(f"LABBY_X_API_PROVIDER invalido: {provider}")
