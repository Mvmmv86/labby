import json
from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.dependencies import CurrentMembership
from app.integrations.sales_channels import EvolutionChannelConnector, WebChatbotConnector

SECRET_CONFIG_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "bot_token",
    "client_secret",
    "last_qr_code",
    "secret",
    "token",
    "webhook_secret",
}
CHANNELS_WAITING_FOR_INBOUND = {"telegram", "discord", "whatsapp_cloud"}


class SalesChannelService:
    def __init__(self, db: Session, *, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def list_channels(self, *, current: CurrentMembership) -> dict[str, Any]:
        self._assert_sales_access(current)
        rows = (
            self.db.execute(
                text(
                    """
                    SELECT
                        id,
                        tenant_id,
                        channel_type AS tipo,
                        name AS nome,
                        status,
                        config,
                        webhook_secret,
                        last_event_at AS ultimo_evento_at,
                        created_at,
                        updated_at
                    FROM sales_channels
                    WHERE tenant_id = :tenant_id
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {"tenant_id": str(current.tenant_id)},
            )
            .mappings()
            .all()
        )
        return {"channels": [self._channel_row(row) for row in rows]}

    def get_channel(self, *, current: CurrentMembership, channel_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        row = self._get_channel_row(tenant_id=str(current.tenant_id), channel_id=channel_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Canal nao encontrado")
        return self._channel_row(row)

    def create_channel(
        self,
        *,
        current: CurrentMembership,
        tipo: str,
        nome: str,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_admin_access(current)
        row = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_channels (
                        tenant_id, channel_type, name, config, webhook_secret
                    )
                    VALUES (
                        :tenant_id, :channel_type, :name, CAST(:config AS jsonb),
                        encode(gen_random_bytes(32), 'hex')
                    )
                    RETURNING
                        id,
                        tenant_id,
                        channel_type AS tipo,
                        name AS nome,
                        status,
                        config,
                        webhook_secret,
                        last_event_at AS ultimo_evento_at,
                        created_at,
                        updated_at
                    """
                ),
                {
                    "tenant_id": str(current.tenant_id),
                    "channel_type": tipo,
                    "name": self._required_string(nome, "Nome do canal e obrigatorio"),
                    "config": self._json_object(config or {}),
                },
            )
            .mappings()
            .one()
        )
        self.db.commit()
        return self._channel_row(row)

    def update_channel(
        self,
        *,
        current: CurrentMembership,
        channel_id: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_admin_access(current)
        updates = ["updated_at = NOW()"]
        params: dict[str, Any] = {
            "tenant_id": str(current.tenant_id),
            "channel_id": UUID(str(channel_id)),
        }
        if "nome" in patch:
            updates.append("name = :name")
            params["name"] = self._required_string(
                patch["nome"],
                "Nome do canal nao pode ser vazio",
            )
        if "config" in patch:
            updates.append("config = config || CAST(:config AS jsonb)")
            params["config"] = self._json_object(patch["config"] or {})
        if len(updates) == 1:
            raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

        row = (
            self.db.execute(
                text(
                    f"""
                    UPDATE sales_channels
                    SET {", ".join(updates)}
                    WHERE id = :channel_id
                      AND tenant_id = :tenant_id
                    RETURNING
                        id,
                        tenant_id,
                        channel_type AS tipo,
                        name AS nome,
                        status,
                        config,
                        webhook_secret,
                        last_event_at AS ultimo_evento_at,
                        created_at,
                        updated_at
                    """
                ),
                params,
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Canal nao encontrado")
        self.db.commit()
        return self._channel_row(row)

    def delete_channel(self, *, current: CurrentMembership, channel_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_admin_access(current)
        row = (
            self.db.execute(
                text(
                    """
                    DELETE FROM sales_channels
                    WHERE id = :channel_id
                      AND tenant_id = :tenant_id
                    RETURNING id
                    """
                ),
                {"tenant_id": str(current.tenant_id), "channel_id": UUID(str(channel_id))},
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Canal nao encontrado")
        self.db.commit()
        return {"id": row["id"], "message": "Canal removido com sucesso"}

    async def connect_channel(
        self,
        *,
        current: CurrentMembership,
        channel_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_admin_access(current)
        row = self._get_channel_row(tenant_id=str(current.tenant_id), channel_id=channel_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Canal nao encontrado")

        channel_type = str(row["tipo"])
        config = dict(row["config"] or {})
        data = data or {}

        if channel_type == "whatsapp_evolution":
            result = await EvolutionChannelConnector(self.settings).connect(
                channel_id=channel_id,
                tenant_id=str(current.tenant_id),
                webhook_secret=str(row["webhook_secret"] or ""),
                existing_config=config,
            )
            self._save_connection_result(
                channel_id,
                str(current.tenant_id),
                result.status,
                result.config,
            )
            return result.response

        if channel_type == "web_chatbot":
            result = WebChatbotConnector(self.settings).connect(
                channel_id=channel_id,
                existing_config=config,
                greeting=data.get("greeting"),
                position=data.get("position"),
                widget_color=data.get("widget_color"),
            )
            self._save_connection_result(
                channel_id,
                str(current.tenant_id),
                result.status,
                result.config,
            )
            return result.response

        if channel_type in CHANNELS_WAITING_FOR_INBOUND:
            raise HTTPException(
                status_code=501,
                detail=(
                    "Conexao deste canal aguarda o receiver de webhook inbound "
                    "da Labby"
                ),
            )

        if channel_type == "telegram":
            return await self._connect_telegram(channel_id, str(current.tenant_id), row, data)

        if channel_type == "discord":
            return await self._connect_discord(channel_id, str(current.tenant_id), data)

        if channel_type == "whatsapp_cloud":
            return await self._connect_whatsapp_cloud(channel_id, str(current.tenant_id), data)

        raise HTTPException(status_code=400, detail=f"Tipo de canal nao suportado: {channel_type}")

    def disconnect_channel(
        self,
        *,
        current: CurrentMembership,
        channel_id: str,
    ) -> dict[str, Any]:
        self._assert_sales_access(current)
        self._assert_admin_access(current)
        row = (
            self.db.execute(
                text(
                    """
                    UPDATE sales_channels
                    SET status = 'desconectado',
                        config = config || '{"active": false}'::jsonb,
                        updated_at = NOW()
                    WHERE id = :channel_id
                      AND tenant_id = :tenant_id
                    RETURNING id, name, status
                    """
                ),
                {"tenant_id": str(current.tenant_id), "channel_id": UUID(str(channel_id))},
            )
            .mappings()
            .first()
        )
        if row is None:
            self.db.rollback()
            raise HTTPException(status_code=404, detail="Canal nao encontrado")
        self.db.commit()
        return {
            "status": row["status"],
            "message": f"Canal {row['name']} desconectado",
        }

    def channel_status(self, *, current: CurrentMembership, channel_id: str) -> dict[str, Any]:
        self._assert_sales_access(current)
        row = self._get_channel_row(tenant_id=str(current.tenant_id), channel_id=channel_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Canal nao encontrado")
        config = dict(row["config"] or {})
        response = {
            "id": row["id"],
            "tipo": row["tipo"],
            "nome": row["nome"],
            "status": row["status"],
            "numero": config.get("phone_number"),
            "phone_number": config.get("phone_number"),
            "bot_username": config.get("bot_username"),
            "guild_name": config.get("guild_name"),
            "widget_id": config.get("widget_id"),
            "ultimo_evento_at": row["ultimo_evento_at"],
        }
        if row["tipo"] == "web_chatbot":
            response["config"] = {
                "color": config.get("color", "#00d4aa"),
                "greeting": config.get("greeting", "Ola! Como posso ajudar?"),
                "position": config.get("position", "bottom-right"),
            }
        return response

    async def _connect_telegram(
        self,
        channel_id: str,
        tenant_id: str,
        row,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        bot_token = str(data.get("bot_token") or "").strip()
        if not bot_token:
            raise HTTPException(status_code=400, detail="bot_token e obrigatorio para Telegram")

        self._mark_connecting(channel_id, tenant_id)
        webhook_url = (
            f"{self.settings.public_api_base_url.rstrip('/')}"
            f"/api/v2/labby/webhooks/telegram/{channel_id}"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                me_response = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
                me_payload = me_response.json()
                if not me_payload.get("ok"):
                    self._mark_error(channel_id, tenant_id)
                    return {
                        "status": "erro",
                        "message": "Token invalido. Verifique o token do bot.",
                    }

                bot_info = me_payload["result"]
                bot_username = bot_info.get("username", "")
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/setWebhook",
                    json={
                        "url": webhook_url,
                        "secret_token": row["webhook_secret"],
                    },
                )
        except httpx.RequestError as exc:
            self._mark_error(channel_id, tenant_id)
            return {"status": "erro", "message": f"Erro de conexao: {exc}"}

        config = {
            "bot_token": bot_token,
            "bot_username": bot_username,
            "bot_name": bot_info.get("first_name", ""),
            "webhook_url": webhook_url,
        }
        self._save_connection_result(channel_id, tenant_id, "conectado", config)
        return {
            "status": "conectado",
            "bot_username": f"@{bot_username}" if bot_username else None,
            "bot_name": bot_info.get("first_name", ""),
            "message": f"Bot @{bot_username} conectado com sucesso.",
        }

    async def _connect_discord(
        self,
        channel_id: str,
        tenant_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        bot_token = str(data.get("bot_token") or "").strip()
        if not bot_token:
            raise HTTPException(status_code=400, detail="bot_token e obrigatorio para Discord")

        self._mark_connecting(channel_id, tenant_id)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                me_response = await client.get(
                    "https://discord.com/api/v10/users/@me",
                    headers={"Authorization": f"Bot {bot_token}"},
                )
                if me_response.status_code != 200:
                    self._mark_error(channel_id, tenant_id)
                    return {
                        "status": "erro",
                        "message": "Token invalido. Verifique o token do bot.",
                    }
                bot_info = me_response.json()
        except httpx.RequestError as exc:
            self._mark_error(channel_id, tenant_id)
            return {"status": "erro", "message": f"Erro de conexao: {exc}"}

        application_id = bot_info.get("id", "")
        permissions = 2048 + 1024 + 65536 + 16384
        oauth_url = (
            "https://discord.com/api/oauth2/authorize"
            f"?client_id={application_id}&permissions={permissions}&scope=bot%20applications.commands"
        )
        config = {
            "bot_token": bot_token,
            "bot_username": bot_info.get("username", ""),
            "bot_name": bot_info.get("username", ""),
            "application_id": application_id,
            "oauth_url": oauth_url,
        }
        self._save_connection_result(channel_id, tenant_id, "conectado", config)
        return {
            "status": "conectado",
            "bot_username": bot_info.get("username", ""),
            "oauth_url": oauth_url,
            "message": f"Bot {bot_info.get('username', '')} validado.",
        }

    async def _connect_whatsapp_cloud(
        self,
        channel_id: str,
        tenant_id: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        phone_number_id = str(data.get("phone_number_id") or "").strip()
        access_token = str(data.get("access_token") or "").strip()
        if not phone_number_id or not access_token:
            raise HTTPException(
                status_code=400,
                detail="phone_number_id e access_token sao obrigatorios",
            )

        self._mark_connecting(channel_id, tenant_id)
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(
                    f"https://graph.facebook.com/v18.0/{phone_number_id}",
                    params={"access_token": access_token},
                )
                if response.status_code != 200:
                    self._mark_error(channel_id, tenant_id)
                    return {
                        "status": "erro",
                        "message": (
                            "Credenciais invalidas. Verifique Phone Number ID e Access Token."
                        ),
                    }
                phone_data = response.json()
        except httpx.RequestError as exc:
            self._mark_error(channel_id, tenant_id)
            return {"status": "erro", "message": f"Erro de conexao: {exc}"}

        phone_number = phone_data.get("display_phone_number", phone_number_id)
        config = {
            "phone_number_id": phone_number_id,
            "access_token": access_token,
            "waba_id": data.get("waba_id"),
            "phone_number": phone_number,
            "verified_name": phone_data.get("verified_name", ""),
        }
        self._save_connection_result(channel_id, tenant_id, "conectado", config)
        return {
            "status": "conectado",
            "phone_number": phone_number,
            "numero": phone_number,
            "message": f"WhatsApp Cloud API conectado ({phone_number}).",
        }

    def _get_channel_row(self, *, tenant_id: str, channel_id: str):
        return (
            self.db.execute(
                text(
                    """
                    SELECT
                        id,
                        tenant_id,
                        channel_type AS tipo,
                        name AS nome,
                        status,
                        config,
                        webhook_secret,
                        last_event_at AS ultimo_evento_at,
                        created_at,
                        updated_at
                    FROM sales_channels
                    WHERE id = :channel_id
                      AND tenant_id = :tenant_id
                    """
                ),
                {"tenant_id": tenant_id, "channel_id": UUID(str(channel_id))},
            )
            .mappings()
            .first()
        )

    def _mark_connecting(self, channel_id: str, tenant_id: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_channels
                SET status = 'conectando', updated_at = NOW()
                WHERE id = :channel_id
                  AND tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id, "channel_id": UUID(str(channel_id))},
        )
        self.db.commit()

    def _mark_error(self, channel_id: str, tenant_id: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_channels
                SET status = 'erro', updated_at = NOW()
                WHERE id = :channel_id
                  AND tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id, "channel_id": UUID(str(channel_id))},
        )
        self.db.commit()

    def _save_connection_result(
        self,
        channel_id: str,
        tenant_id: str,
        status: str,
        config: dict[str, Any],
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_channels
                SET status = :status,
                    config = config || CAST(:config AS jsonb),
                    last_event_at = CASE
                        WHEN :status = 'conectado' THEN NOW()
                        ELSE last_event_at
                    END,
                    updated_at = NOW()
                WHERE id = :channel_id
                  AND tenant_id = :tenant_id
                """
            ),
            {
                "status": status,
                "config": self._json_object(config),
                "tenant_id": tenant_id,
                "channel_id": UUID(str(channel_id)),
            },
        )
        self.db.commit()

    @staticmethod
    def _assert_sales_access(current: CurrentMembership) -> None:
        if current.role == "owner":
            return
        if "sales" not in current.modules:
            raise HTTPException(status_code=403, detail="Modulo sales nao habilitado")

    @staticmethod
    def _assert_admin_access(current: CurrentMembership) -> None:
        if current.role not in {"owner", "admin"}:
            raise HTTPException(
                status_code=403,
                detail="Apenas owner ou admin podem gerenciar canais",
            )

    @classmethod
    def _channel_row(cls, row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tenant_id": row["tenant_id"],
            "tipo": row["tipo"],
            "nome": row["nome"],
            "status": row["status"],
            "config": cls._redact_config(row["config"] or {}),
            "webhook_configured": bool(row["webhook_secret"]),
            "ultimo_evento_at": row["ultimo_evento_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    @classmethod
    def _redact_config(cls, config: Any) -> dict[str, Any]:
        if not isinstance(config, dict):
            return {}
        redacted: dict[str, Any] = {}
        for key, value in config.items():
            key_lower = str(key).lower()
            if (
                key_lower in SECRET_CONFIG_KEYS
                or key_lower.endswith("_token")
                or key_lower.endswith("_secret")
            ):
                redacted[key] = "***" if value else None
            elif isinstance(value, dict):
                redacted[key] = cls._redact_config(value)
            elif isinstance(value, list):
                redacted[key] = [
                    cls._redact_config(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                redacted[key] = value
        return redacted

    @staticmethod
    def _required_string(value: str | None, message: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail=message)
        return cleaned

    @staticmethod
    def _json_object(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False)
