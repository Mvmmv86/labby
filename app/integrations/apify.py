from functools import lru_cache
from typing import Any

import httpx

from app.core.config import Settings


class ApifyConfigurationError(Exception):
    pass


class ApifyProviderError(Exception):
    pass


class ApifyClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def fetch_instagram_profile(self, *, handle: str) -> list[dict[str, Any]]:
        return self._run_actor_sync_get_dataset_items(
            actor_id=self.settings.apify_instagram_profile_actor_id,
            payload={"usernames": [handle]},
            max_items=1,
        )

    def fetch_instagram_posts(self, *, handle: str, limit: int) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(limit, 100))
        return self._run_actor_sync_get_dataset_items(
            actor_id=self.settings.apify_instagram_post_actor_id,
            payload={
                "username": [handle],
                "resultsLimit": bounded_limit,
                "dataDetailLevel": "basicData",
            },
            max_items=bounded_limit,
        )

    def _run_actor_sync_get_dataset_items(
        self,
        *,
        actor_id: str,
        payload: dict[str, Any],
        max_items: int,
    ) -> list[dict[str, Any]]:
        token = self.settings.apify_api_token
        if not token:
            raise ApifyConfigurationError("LABBY_APIFY_API_TOKEN nao configurado")

        base_url = self.settings.apify_api_base_url.rstrip("/")
        actor_path = actor_id.strip().replace("/", "~")
        client = _get_http_client(
            base_url=base_url,
            timeout_seconds=self.settings.apify_timeout_seconds,
        )
        params: dict[str, str] = {
            "clean": "true",
            "format": "json",
            "maxItems": str(max_items),
        }
        if self.settings.apify_max_total_charge_usd > 0:
            params["maxTotalChargeUsd"] = str(self.settings.apify_max_total_charge_usd)

        try:
            response = client.post(
                f"{base_url}/acts/{actor_path}/run-sync-get-dataset-items",
                json=payload,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ApifyProviderError("Apify indisponivel") from exc

        if response.status_code >= 400:
            message = _extract_error_message(_safe_json(response))
            raise ApifyProviderError(message or f"Apify retornou HTTP {response.status_code}")

        data = response.json()
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("data", "items", "results"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            return [data] if data else []
        return []


@lru_cache(maxsize=8)
def _get_http_client(*, base_url: str, timeout_seconds: float) -> httpx.Client:
    return httpx.Client(timeout=timeout_seconds)


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
