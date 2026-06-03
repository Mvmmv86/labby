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


@dataclass(frozen=True)
class OutboundSendResult:
    provider: str
    external_id: str
    response: dict[str, Any]


class OutboundProviderError(Exception):
    pass


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


class EvolutionOutboundAdapter:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_message(
        self,
        *,
        channel_config: dict[str, Any],
        recipient_identifier: str,
        message_type: str,
        content: str | None,
        media_url: str | None,
        media_caption: str | None,
        idempotency_key: str,
    ) -> OutboundSendResult:
        if not self.settings.evolution_api_url or not self.settings.evolution_api_key:
            raise OutboundProviderError(
                "LABBY_EVOLUTION_API_URL e LABBY_EVOLUTION_API_KEY nao configurados"
            )

        instance_name = str(channel_config.get("instance_name") or "").strip()
        if not instance_name:
            raise OutboundProviderError("Canal Evolution sem instance_name")

        number = _evolution_number(recipient_identifier)
        if not number:
            raise OutboundProviderError("Destinatario Evolution sem numero")

        base_url = self.settings.evolution_api_url.rstrip("/")
        headers = {"apikey": self.settings.evolution_api_key}
        endpoint, payload = _evolution_payload(
            instance_name=instance_name,
            number=number,
            message_type=message_type,
            content=content,
            media_url=media_url,
            media_caption=media_caption,
            idempotency_key=idempotency_key,
        )

        async with httpx.AsyncClient(timeout=self.settings.evolution_api_timeout_seconds) as client:
            response = await client.post(
                f"{base_url}{endpoint}",
                json=payload,
                headers=headers,
            )

        response_payload = _safe_json(response)
        if response.status_code >= 400:
            raise OutboundProviderError(
                str(response_payload.get("message") or response_payload or response.text)
            )

        external_id = _extract_outbound_external_id(response_payload)
        if not external_id:
            raise OutboundProviderError("Evolution nao retornou external id da mensagem")

        return OutboundSendResult(
            provider="evolution",
            external_id=external_id,
            response=response_payload,
        )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _evolution_number(identifier: str) -> str:
    cleaned = str(identifier or "").strip()
    if "@" in cleaned:
        cleaned = cleaned.split("@", 1)[0]
    return "".join(character for character in cleaned if character.isdigit())


def _evolution_payload(
    *,
    instance_name: str,
    number: str,
    message_type: str,
    content: str | None,
    media_url: str | None,
    media_caption: str | None,
    idempotency_key: str,
) -> tuple[str, dict[str, Any]]:
    metadata = {"labby_idempotency_key": idempotency_key}
    if message_type == "text":
        return (
            f"/message/sendText/{instance_name}",
            {
                "number": number,
                "text": content or "",
                "delay": 0,
                "metadata": metadata,
            },
        )

    if message_type in {"image", "video", "document"} and media_url:
        return (
            f"/message/sendMedia/{instance_name}",
            {
                "number": number,
                "mediatype": message_type,
                "media": media_url,
                "caption": media_caption or content or "",
                "delay": 0,
                "metadata": metadata,
            },
        )

    raise OutboundProviderError(f"Tipo de mensagem nao suportado para Evolution: {message_type}")


def _extract_outbound_external_id(payload: dict[str, Any]) -> str | None:
    key = payload.get("key")
    if isinstance(key, dict) and key.get("id"):
        return str(key["id"])

    for key_name in ("id", "messageId", "message_id"):
        if payload.get(key_name):
            return str(payload[key_name])

    message = payload.get("message")
    if isinstance(message, dict):
        message_key = message.get("key")
        if isinstance(message_key, dict) and message_key.get("id"):
            return str(message_key["id"])
        for key_name in ("id", "messageId", "message_id"):
            if message.get(key_name):
                return str(message[key_name])

    return None
