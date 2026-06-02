import secrets
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings


@dataclass(frozen=True)
class ChannelConnectionResult:
    status: str
    config: dict[str, Any]
    response: dict[str, Any]


class EvolutionChannelConnector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def connect(
        self,
        *,
        channel_id: str,
        tenant_id: str,
        webhook_secret: str,
        existing_config: dict[str, Any] | None = None,
    ) -> ChannelConnectionResult:
        config = dict(existing_config or {})
        instance_name = config.get("instance_name") or f"labby_{tenant_id[:8]}_{channel_id[:8]}"
        webhook_url = (
            f"{self.settings.public_api_base_url.rstrip('/')}"
            f"/api/v2/labby/webhooks/evolution/{channel_id}"
        )
        config.update(
            {
                "instance_name": instance_name,
                "webhook_url": webhook_url,
                "provider_configured": bool(
                    self.settings.evolution_api_url and self.settings.evolution_api_key
                ),
            }
        )

        if not self.settings.evolution_api_url or not self.settings.evolution_api_key:
            return ChannelConnectionResult(
                status="conectando",
                config=config,
                response={
                    "status": "conectando",
                    "qr_code": "",
                    "instance_name": instance_name,
                    "message": (
                        "LABBY_EVOLUTION_API_URL e LABBY_EVOLUTION_API_KEY nao configurados."
                    ),
                },
            )

        base_url = self.settings.evolution_api_url.rstrip("/")
        headers = {"apikey": self.settings.evolution_api_key}
        async with httpx.AsyncClient(timeout=self.settings.evolution_api_timeout_seconds) as client:
            state_response = await client.get(
                f"{base_url}/instance/connectionState/{instance_name}",
                headers=headers,
            )
            instance_exists = state_response.status_code == 200
            if instance_exists:
                state_payload = _safe_json(state_response)
                state = state_payload.get("instance", {}).get("state", "")
                if state == "open":
                    config["state"] = state
                    return ChannelConnectionResult(
                        status="conectado",
                        config=config,
                        response={
                            "status": "conectado",
                            "instance_name": instance_name,
                            "message": "WhatsApp ja esta conectado.",
                        },
                    )
            else:
                await client.post(
                    f"{base_url}/instance/create",
                    json={
                        "instanceName": instance_name,
                        "qrcode": True,
                        "integration": "WHATSAPP-BAILEYS",
                    },
                    headers=headers,
                )

            await client.post(
                f"{base_url}/webhook/set/{instance_name}",
                json={
                    "url": webhook_url,
                    "webhook_by_events": False,
                    "webhook_base64": False,
                    "headers": {
                        "X-Labby-Webhook-Secret": webhook_secret,
                    },
                    "events": [
                        "MESSAGES_UPSERT",
                        "MESSAGES_UPDATE",
                        "CONNECTION_UPDATE",
                        "QRCODE_UPDATED",
                    ],
                },
                headers=headers,
            )

            qr_response = await client.get(
                f"{base_url}/instance/connect/{instance_name}",
                headers=headers,
            )
            qr_payload = _safe_json(qr_response) if qr_response.status_code == 200 else {}
            qr_code = qr_payload.get("base64") or qr_payload.get("qrcode", {}).get("base64", "")
            if qr_code:
                config["last_qr_code"] = qr_code

        return ChannelConnectionResult(
            status="conectando",
            config=config,
            response={
                "status": "conectando",
                "qr_code": qr_code,
                "instance_name": instance_name,
                "message": "Escaneie o QR code com seu WhatsApp.",
            },
        )


class WebChatbotConnector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def connect(
        self,
        *,
        channel_id: str,
        existing_config: dict[str, Any] | None = None,
        greeting: str | None = None,
        position: str | None = None,
        widget_color: str | None = None,
    ) -> ChannelConnectionResult:
        config = dict(existing_config or {})
        widget_id = config.get("widget_id") or f"labby_{secrets.token_hex(12)}"
        config.update(
            {
                "widget_id": widget_id,
                "greeting": greeting or config.get("greeting") or "Ola! Como posso ajudar?",
                "position": position or config.get("position") or "bottom-right",
                "color": widget_color or config.get("color") or "#00d4aa",
                "active": True,
            }
        )
        snippet = (
            f'<script src="{self.settings.public_api_base_url.rstrip("/")}'
            f'/widget/{widget_id}/loader.js" async></script>'
        )
        return ChannelConnectionResult(
            status="conectado",
            config=config,
            response={
                "status": "conectado",
                "widget_id": widget_id,
                "snippet": snippet,
                "message": "Widget configurado. Cole o snippet no seu site.",
            },
        )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
