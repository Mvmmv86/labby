import httpx
import pytest

from app.core.config import Settings
from app.integrations import apify
from app.integrations.apify import ApifyClient, ApifyConfigurationError, ApifyProviderError


def make_settings() -> Settings:
    return Settings(
        environment="development",
        apify_api_base_url="https://api.apify.test/v2",
        apify_api_token="token-secret",
        apify_timeout_seconds=10.0,
        apify_instagram_profile_actor_id="apify/instagram-profile-scraper",
        apify_instagram_post_actor_id="apify/instagram-post-scraper",
        apify_instagram_max_posts_per_profile=24,
    )


def test_apify_profile_uses_bearer_auth_and_tilde_actor_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    original_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[{"username": "gvcripto"}])

    monkeypatch.setattr(
        apify.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    apify._get_http_client.cache_clear()

    result = ApifyClient(make_settings()).fetch_instagram_profile(handle="gvcripto")

    assert result == [{"username": "gvcripto"}]
    assert len(requests) == 1
    assert "/acts/apify~instagram-profile-scraper/run-sync-get-dataset-items" in str(
        requests[0].url
    )
    assert "token-secret" not in str(requests[0].url)
    assert requests[0].headers["authorization"] == "Bearer token-secret"
    assert requests[0].read() == b'{"usernames":["gvcripto"]}'


def test_apify_posts_do_not_retry_post_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500, json={"error": {"message": "boom"}})

    monkeypatch.setattr(
        apify.httpx,
        "Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    apify._get_http_client.cache_clear()

    with pytest.raises(ApifyProviderError):
        ApifyClient(make_settings()).fetch_instagram_posts(handle="gvcripto", limit=30)

    assert calls == 1


def test_apify_requires_server_side_token() -> None:
    settings = make_settings()
    settings.apify_api_token = None

    with pytest.raises(ApifyConfigurationError):
        ApifyClient(settings).fetch_instagram_profile(handle="gvcripto")
