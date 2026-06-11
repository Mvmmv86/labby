import httpx
import pytest

from app.core.config import Settings
from app.integrations import phyllo
from app.integrations.phyllo import PhylloClient, PhylloProviderError


def make_settings() -> Settings:
    return Settings(
        phyllo_client_id="client-id",
        phyllo_client_secret="client-secret",
        phyllo_api_base_url="https://api.staging.getphyllo.test",
    )


def test_phyllo_get_retries_transient_5xx(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(502, json={"message": "temporarily unavailable"})
        return httpx.Response(200, json={"data": [{"id": "account-1"}]})

    original_client = httpx.Client
    monkeypatch.setattr(phyllo.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        phyllo.httpx,
        "Client",
        lambda **_kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    phyllo._get_http_client.cache_clear()

    accounts = PhylloClient(make_settings()).list_accounts(user_id="user-1")

    assert accounts == [{"id": "account-1"}]
    assert len(calls) == 2


def test_phyllo_post_does_not_retry_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502, json={"message": "temporarily unavailable"})

    original_client = httpx.Client
    monkeypatch.setattr(
        phyllo.httpx,
        "Client",
        lambda **_kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    phyllo._get_http_client.cache_clear()

    with pytest.raises(PhylloProviderError):
        PhylloClient(make_settings()).create_user(name="Marcus", external_id="tenant-1")

    assert calls == 1


def test_phyllo_http_client_is_reused(monkeypatch: pytest.MonkeyPatch) -> None:
    client_creations = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    original_client = httpx.Client

    def make_client(**_kwargs):
        nonlocal client_creations
        client_creations += 1
        return original_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(phyllo.httpx, "Client", make_client)
    phyllo._get_http_client.cache_clear()

    client = PhylloClient(make_settings())
    client.list_accounts(user_id="user-1")
    client.list_accounts(user_id="user-1")

    assert client_creations == 1


def test_phyllo_lists_social_contents(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "content-1",
                        "engagement": {"like_count": 10, "share_count": 2},
                    }
                ]
            },
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        phyllo.httpx,
        "Client",
        lambda **_kwargs: original_client(transport=httpx.MockTransport(handler)),
    )
    phyllo._get_http_client.cache_clear()

    contents = PhylloClient(make_settings()).list_contents(account_id="account-1", limit=10)

    assert contents == [{"id": "content-1", "engagement": {"like_count": 10, "share_count": 2}}]
    assert "/v1/social/contents" in captured[0]
    assert "account_id=account-1" in captured[0]
    assert "limit=10" in captured[0]
