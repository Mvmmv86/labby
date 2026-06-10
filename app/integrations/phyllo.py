import time
from functools import lru_cache
from typing import Any

import httpx

from app.core.config import Settings


class PhylloConfigurationError(Exception):
    pass


class PhylloProviderError(Exception):
    pass


_GET_RETRY_DELAYS_SECONDS = (0.2, 0.5)


class PhylloClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def get_user_by_external_id(self, external_id: str) -> dict[str, Any] | None:
        return self._request(
            "GET",
            f"/v1/users/external_id/{external_id}",
            allow_not_found=True,
        )

    def create_user(self, *, name: str, external_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/users",
            json={"name": name, "external_id": external_id},
        )

    def create_sdk_token(self, *, user_id: str, products: list[str]) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v1/sdk-tokens",
            json={"user_id": user_id, "products": products},
        )

    def get_account(self, account_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/accounts/{account_id}")

    def list_accounts(self, *, user_id: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            "/v1/accounts",
            params={"user_id": user_id},
        )
        return _extract_collection(payload)

    def list_profiles(self, *, account_id: str) -> list[dict[str, Any]]:
        payload = self._request(
            "GET",
            "/v1/profiles",
            params={"account_id": account_id},
        )
        return _extract_collection(payload)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        if not self.settings.phyllo_client_id or not self.settings.phyllo_client_secret:
            raise PhylloConfigurationError("LABBY_PHYLLO_CLIENT_ID/SECRET nao configurados")

        base_url = self.settings.phyllo_api_base_url.rstrip("/")
        client = _get_http_client(
            base_url=base_url,
            timeout_seconds=self.settings.phyllo_timeout_seconds,
            client_id=self.settings.phyllo_client_id,
            client_secret=self.settings.phyllo_client_secret,
        )
        attempts = 1 + (len(_GET_RETRY_DELAYS_SECONDS) if method.upper() == "GET" else 0)
        response: httpx.Response | None = None
        for attempt in range(attempts):
            try:
                response = client.request(
                    method,
                    f"{base_url}{path}",
                    json=json,
                    params=params,
                    headers={"Content-Type": "application/json"},
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == attempts - 1:
                    raise PhylloProviderError("Phyllo indisponivel") from exc
                time.sleep(_GET_RETRY_DELAYS_SECONDS[attempt])
                continue
            if response.status_code < 500 or attempt == attempts - 1:
                break
            time.sleep(_GET_RETRY_DELAYS_SECONDS[attempt])

        if response is None:
            raise PhylloProviderError("Phyllo indisponivel")

        if response.status_code == 404 and allow_not_found:
            return None
        payload = _safe_json(response)
        if response.status_code >= 400:
            message = (
                _extract_error_message(payload)
                or f"Phyllo retornou HTTP {response.status_code}"
            )
            raise PhylloProviderError(message)
        return payload


@lru_cache(maxsize=8)
def _get_http_client(
    *,
    base_url: str,
    timeout_seconds: float,
    client_id: str,
    client_secret: str,
) -> httpx.Client:
    return httpx.Client(
        timeout=timeout_seconds,
        auth=httpx.BasicAuth(client_id, client_secret),
    )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_error_message(payload: dict[str, Any]) -> str | None:
    for key in ("message", "error", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = _extract_error_message(value)
            if nested:
                return nested
    return None


def _extract_collection(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    for key in ("data", "profiles", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload] if payload.get("id") else []
