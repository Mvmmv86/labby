import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domains.sales.bot_service import SalesBotService

WIDGET_PROVIDER = "web_widget"
WIDGET_MESSAGE_LIMIT_PER_IP_PER_MINUTE = 20
WIDGET_MESSAGE_LIMIT_PER_WIDGET_PER_MINUTE = 120
WIDGET_POLL_LIMIT_PER_IP_PER_MINUTE = 90
WIDGET_POLL_LIMIT_PER_WIDGET_PER_MINUTE = 600


class PublicWidgetService:
    def __init__(self, db: Session, *, bot_service: SalesBotService | None = None) -> None:
        self.db = db
        self.bot_service = bot_service or SalesBotService(db)

    def loader_js(self, *, widget_id: str, api_origin: str, origin: str | None = None) -> str:
        channel = self._widget_channel(widget_id=widget_id, require_active=True)
        if channel is None:
            return "/* Labby widget not found or inactive */"
        self._assert_origin_allowed(channel=channel, origin=origin)
        config = dict(channel["config"] or {})
        return build_widget_js(
            widget_id=widget_id,
            color=str(config.get("color") or "#00d4aa"),
            greeting=str(config.get("greeting") or "Ola! Como posso ajudar?"),
            position=str(config.get("position") or "bottom-right"),
            name=str(channel["name"] or "Labby Chat"),
            api_origin=api_origin,
        )

    def config(self, *, widget_id: str, origin: str | None = None) -> dict[str, Any]:
        channel = self._widget_channel(widget_id=widget_id, require_active=True)
        if channel is None:
            raise HTTPException(status_code=404, detail="Widget nao encontrado")
        self._assert_origin_allowed(channel=channel, origin=origin)
        config = dict(channel["config"] or {})
        return {
            "widget_id": widget_id,
            "color": str(config.get("color") or "#00d4aa"),
            "greeting": str(config.get("greeting") or "Ola! Como posso ajudar?"),
            "position": str(config.get("position") or "bottom-right"),
            "name": str(channel["name"] or "Labby Chat"),
            "active": True,
        }

    def receive_message(
        self,
        *,
        widget_id: str,
        visitor_id: str,
        visitor_name: str | None,
        message: str,
        client_message_id: str | None,
        client_ip: str,
        origin: str | None = None,
    ) -> dict[str, Any]:
        channel = self._widget_channel(widget_id=widget_id, require_active=True)
        if channel is None:
            raise HTTPException(status_code=404, detail="Widget nao encontrado")
        self._assert_origin_allowed(channel=channel, origin=origin)
        tenant_id = str(channel["tenant_id"])
        channel_id = str(channel["id"])
        cleaned_visitor_id = self._required_string(visitor_id, "visitor_id obrigatorio")[:160]
        cleaned_message = self._required_string(message, "Mensagem vazia")[:4000]
        cleaned_name = self._optional_string(visitor_name) or f"Visitante {cleaned_visitor_id[:8]}"

        self._enforce_widget_rate_limits(
            tenant_id=tenant_id,
            action="widget.message",
            widget_id=widget_id,
            client_ip=client_ip,
            ip_limit=WIDGET_MESSAGE_LIMIT_PER_IP_PER_MINUTE,
            widget_limit=WIDGET_MESSAGE_LIMIT_PER_WIDGET_PER_MINUTE,
        )

        try:
            self._lock_visitor(
                tenant_id=tenant_id,
                widget_id=widget_id,
                visitor_id=cleaned_visitor_id,
            )
            contact_id = self._upsert_contact(
                tenant_id=tenant_id,
                channel_id=channel_id,
                widget_id=widget_id,
                visitor_id=cleaned_visitor_id,
                visitor_name=cleaned_name,
            )
            conversation_id = self._get_or_create_conversation(
                tenant_id=tenant_id,
                channel_id=channel_id,
                contact_id=contact_id,
            )
            external_id = self._message_external_id(
                widget_id=widget_id,
                visitor_id=cleaned_visitor_id,
                client_message_id=client_message_id,
                message=cleaned_message,
            )
            inbound = self._insert_inbound_message(
                tenant_id=tenant_id,
                channel_id=channel_id,
                contact_id=contact_id,
                conversation_id=conversation_id,
                external_id=external_id,
                visitor_id=cleaned_visitor_id,
                message=cleaned_message,
            )
            duplicate = inbound is None
            if duplicate:
                inbound = self._message_by_external_id(
                    tenant_id=tenant_id,
                    external_id=external_id,
                )
                if inbound is None:
                    raise HTTPException(status_code=409, detail="Mensagem duplicada indisponivel")
                bot_response = None
            else:
                self._touch_conversation_after_inbound(
                    tenant_id=tenant_id,
                    contact_id=contact_id,
                    conversation_id=conversation_id,
                    created_at=inbound["created_at"],
                )
                bot_response = self.bot_service.maybe_respond_to_widget_message(
                    tenant_id=tenant_id,
                    channel_id=channel_id,
                    conversation_id=conversation_id,
                    contact_id=contact_id,
                    input_message_id=str(inbound["id"]),
                    message_text=cleaned_message,
                    widget_id=widget_id,
                )

            last_message_id = self._last_message_id(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
            )
            self.db.commit()
            return {
                "status": "ok",
                "conversa_id": UUID(str(conversation_id)),
                "conversation_id": UUID(str(conversation_id)),
                "message_id": UUID(str(inbound["id"])),
                "duplicate": duplicate,
                "bot_response": bot_response,
                "last_message_id": UUID(str(last_message_id or inbound["id"])),
            }
        except HTTPException:
            self.db.rollback()
            raise
        except Exception as exc:
            self.db.rollback()
            raise HTTPException(status_code=500, detail="Erro ao processar mensagem") from exc

    def list_messages(
        self,
        *,
        widget_id: str,
        visitor_id: str,
        after: str | None,
        client_ip: str,
        origin: str | None = None,
    ) -> dict[str, Any]:
        channel = self._widget_channel(widget_id=widget_id, require_active=True)
        if channel is None:
            raise HTTPException(status_code=404, detail="Widget nao encontrado")
        self._assert_origin_allowed(channel=channel, origin=origin)
        tenant_id = str(channel["tenant_id"])
        channel_id = str(channel["id"])
        cleaned_visitor_id = self._required_string(visitor_id, "visitor_id obrigatorio")[:160]

        self._enforce_widget_rate_limits(
            tenant_id=tenant_id,
            action="widget.poll",
            widget_id=widget_id,
            client_ip=client_ip,
            ip_limit=WIDGET_POLL_LIMIT_PER_IP_PER_MINUTE,
            widget_limit=WIDGET_POLL_LIMIT_PER_WIDGET_PER_MINUTE,
        )

        contact_id = self._contact_id_for_visitor(
            tenant_id=tenant_id,
            widget_id=widget_id,
            visitor_id=cleaned_visitor_id,
        )
        if contact_id is None:
            self.db.commit()
            return {"messages": [], "conversation_id": None, "last_message_id": None}

        conversation = (
            self.db.execute(
                text(
                    """
                    SELECT id
                    FROM sales_conversations
                    WHERE tenant_id = :tenant_id
                      AND contact_id = :contact_id
                      AND channel_id = :channel_id
                      AND status != 'fechada'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "contact_id": UUID(str(contact_id)),
                    "channel_id": UUID(channel_id),
                },
            )
            .mappings()
            .first()
        )
        if conversation is None:
            self.db.commit()
            return {"messages": [], "conversation_id": None, "last_message_id": None}

        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "conversation_id": conversation["id"],
        }
        cursor_sql = ""
        cursor = self._message_cursor(
            tenant_id=tenant_id,
            conversation_id=str(conversation["id"]),
            after=after,
        )
        if cursor is not None:
            cursor_sql = """
              AND (
                    created_at > :cursor_created_at
                    OR (created_at = :cursor_created_at AND id > :cursor_id)
              )
            """
            params["cursor_created_at"] = cursor["created_at"]
            params["cursor_id"] = cursor["id"]

        rows = (
            self.db.execute(
                text(
                    f"""
                    SELECT id, content, direction, sender_type, created_at
                    FROM sales_messages
                    WHERE tenant_id = :tenant_id
                      AND conversation_id = :conversation_id
                      {cursor_sql}
                    ORDER BY created_at ASC, id ASC
                    LIMIT 50
                    """
                ),
                params,
            )
            .mappings()
            .all()
        )
        self.db.commit()
        return {
            "messages": [
                {
                    "id": row["id"],
                    "content": row["content"] or "",
                    "direction": row["direction"],
                    "sender_type": row["sender_type"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
            "conversation_id": conversation["id"],
            "last_message_id": rows[-1]["id"] if rows else None,
        }

    def _widget_channel(self, *, widget_id: str, require_active: bool):
        cleaned_widget_id = self._required_string(widget_id, "widget_id obrigatorio")[:160]
        row = (
            self.db.execute(
                text(
                    """
                    SELECT id, tenant_id, name, status, config
                    FROM sales_channels
                    WHERE channel_type = 'web_chatbot'
                      AND config->>'widget_id' = :widget_id
                    LIMIT 1
                    """
                ),
                {"widget_id": cleaned_widget_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        if require_active and (
            str(row["status"]) != "conectado"
            or dict(row["config"] or {}).get("active") is False
        ):
            return None
        return row

    def _assert_origin_allowed(self, *, channel, origin: str | None) -> None:
        allowed = dict(channel["config"] or {}).get("allowed_origins")
        if not allowed or not origin:
            return
        if isinstance(allowed, str):
            allowed_origins = [item.strip() for item in allowed.split(",") if item.strip()]
        elif isinstance(allowed, list):
            allowed_origins = [str(item).strip() for item in allowed if str(item).strip()]
        else:
            return
        if "*" in allowed_origins or origin in allowed_origins:
            return
        raise HTTPException(status_code=403, detail="Origem nao autorizada para este widget")

    def _enforce_widget_rate_limits(
        self,
        *,
        tenant_id: str,
        action: str,
        widget_id: str,
        client_ip: str,
        ip_limit: int,
        widget_limit: int,
    ) -> None:
        self._enforce_rate_limit(
            tenant_id=tenant_id,
            key=self._rate_limit_ip_key(widget_id, client_ip),
            action=f"{action}.ip",
            limit=ip_limit,
            metadata={
                "widget_id": widget_id,
                "scope": "ip",
                "client_ip": client_ip,
            },
        )
        self._enforce_rate_limit(
            tenant_id=tenant_id,
            key=self._rate_limit_widget_key(widget_id),
            action=f"{action}.widget",
            limit=widget_limit,
            metadata={
                "widget_id": widget_id,
                "scope": "widget",
            },
        )

    def _enforce_rate_limit(
        self,
        *,
        tenant_id: str,
        key: str,
        action: str,
        limit: int,
        metadata: dict[str, Any],
    ) -> None:
        current_count = self.db.execute(
            text(
                """
                SELECT COUNT(*)
                FROM rate_limit_events
                WHERE tenant_id = :tenant_id
                  AND provider = :provider
                  AND rate_limit_key = :rate_limit_key
                  AND action = :action
                  AND outcome = 'allowed'
                  AND created_at >= NOW() - INTERVAL '60 seconds'
                """
            ),
            {
                "tenant_id": tenant_id,
                "provider": WIDGET_PROVIDER,
                "rate_limit_key": key,
                "action": action,
            },
        ).scalar_one()
        outcome = "blocked" if int(current_count or 0) >= limit else "allowed"
        self.db.execute(
            text(
                """
                INSERT INTO rate_limit_events (
                    tenant_id, provider, rate_limit_key, action, outcome,
                    retry_after, metadata_json
                )
                VALUES (
                    :tenant_id, :provider, :rate_limit_key, :action, :outcome,
                    CASE WHEN :outcome = 'blocked'
                        THEN NOW() + INTERVAL '60 seconds'
                        ELSE NULL
                    END,
                    CAST(:metadata AS jsonb)
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "provider": WIDGET_PROVIDER,
                "rate_limit_key": key,
                "action": action,
                "outcome": outcome,
                "metadata": self._json_object(metadata),
            },
        )
        if outcome == "blocked":
            self.db.commit()
            raise HTTPException(status_code=429, detail="Limite de mensagens excedido")

    def _upsert_contact(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        widget_id: str,
        visitor_id: str,
        visitor_name: str,
    ) -> str:
        existing = self._contact_id_for_visitor(
            tenant_id=tenant_id,
            widget_id=widget_id,
            visitor_id=visitor_id,
        )
        if existing is not None:
            self.db.execute(
                text(
                    """
                    UPDATE sales_contacts
                    SET name = CASE
                            WHEN name LIKE 'Visitante %' THEN :visitor_name
                            ELSE name
                        END,
                        custom_fields = custom_fields || CAST(:custom_fields AS jsonb),
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND id = :contact_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "contact_id": UUID(str(existing)),
                    "visitor_name": visitor_name,
                    "custom_fields": self._json_object(
                        {
                            "widget_id": widget_id,
                            "visitor_id": visitor_id,
                        }
                    ),
                },
            )
            return str(existing)

        contact = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_contacts (
                        tenant_id, name, tags, custom_fields, status
                    )
                    VALUES (
                        :tenant_id, :name, '["web_chat"]'::jsonb,
                        CAST(:custom_fields AS jsonb), 'active'
                    )
                    RETURNING id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "name": visitor_name,
                    "custom_fields": self._json_object(
                        {
                            "canal": "web_chat",
                            "widget_id": widget_id,
                            "visitor_id": visitor_id,
                        }
                    ),
                },
            )
            .mappings()
            .one()
        )
        self.db.execute(
            text(
                """
                INSERT INTO sales_contact_channels (
                    tenant_id, contact_id, channel_id, channel_type, identifier, metadata
                )
                VALUES (
                    :tenant_id, :contact_id, :channel_id, 'web_chatbot',
                    :identifier, CAST(:metadata AS jsonb)
                )
                """
            ),
            {
                "tenant_id": tenant_id,
                "contact_id": contact["id"],
                "channel_id": UUID(channel_id),
                "identifier": self._visitor_identifier(widget_id, visitor_id),
                "metadata": self._json_object({"widget_id": widget_id, "visitor_id": visitor_id}),
            },
        )
        return str(contact["id"])

    def _contact_id_for_visitor(
        self,
        *,
        tenant_id: str,
        widget_id: str,
        visitor_id: str,
    ) -> str | None:
        row = (
            self.db.execute(
                text(
                    """
                    SELECT contact_id
                    FROM sales_contact_channels
                    WHERE tenant_id = :tenant_id
                      AND channel_type = 'web_chatbot'
                      AND identifier = :identifier
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "identifier": self._visitor_identifier(widget_id, visitor_id),
                },
            )
            .mappings()
            .first()
        )
        return str(row["contact_id"]) if row else None

    def _get_or_create_conversation(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        contact_id: str,
    ) -> str:
        row = (
            self.db.execute(
                text(
                    """
                    SELECT id
                    FROM sales_conversations
                    WHERE tenant_id = :tenant_id
                      AND contact_id = :contact_id
                      AND channel_id = :channel_id
                      AND status != 'fechada'
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "contact_id": UUID(str(contact_id)),
                    "channel_id": UUID(channel_id),
                },
            )
            .mappings()
            .first()
        )
        if row:
            return str(row["id"])

        row = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_conversations (
                        tenant_id, contact_id, channel_id, status, tags,
                        waiting_for_human, last_message_at
                    )
                    VALUES (
                        :tenant_id, :contact_id, :channel_id, 'aberta',
                        '[]'::jsonb, true, NOW()
                    )
                    RETURNING id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "contact_id": UUID(str(contact_id)),
                    "channel_id": UUID(channel_id),
                },
            )
            .mappings()
            .one()
        )
        return str(row["id"])

    def _insert_inbound_message(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        contact_id: str,
        conversation_id: str,
        external_id: str,
        visitor_id: str,
        message: str,
    ):
        return (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_messages (
                        tenant_id, conversation_id, contact_id, direction,
                        sender_type, message_type, content, provider, external_id,
                        status, metadata
                    )
                    VALUES (
                        :tenant_id, :conversation_id, :contact_id, 'entrada',
                        'contato', 'text', :content, 'web_widget', :external_id,
                        'sent', CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (tenant_id, provider, external_id)
                        WHERE provider IS NOT NULL AND external_id IS NOT NULL
                    DO NOTHING
                    RETURNING id, created_at
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": UUID(str(conversation_id)),
                    "contact_id": UUID(str(contact_id)),
                    "content": message,
                    "external_id": external_id,
                    "metadata": self._json_object(
                        {
                            "channel_id": channel_id,
                            "visitor_id": visitor_id,
                        }
                    ),
                },
            )
            .mappings()
            .first()
        )

    def _touch_conversation_after_inbound(
        self,
        *,
        tenant_id: str,
        contact_id: str,
        conversation_id: str,
        created_at,
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_conversations
                SET last_message_at = :created_at,
                    waiting_for_human = true,
                    status = CASE WHEN status = 'fechada' THEN 'aberta' ELSE status END,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :conversation_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "conversation_id": UUID(str(conversation_id)),
                "created_at": created_at,
            },
        )
        self.db.execute(
            text(
                """
                UPDATE sales_contacts
                SET total_messages_received = total_messages_received + 1,
                    last_interaction_at = :created_at,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :contact_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "contact_id": UUID(str(contact_id)),
                "created_at": created_at,
            },
        )

    def _message_by_external_id(self, *, tenant_id: str, external_id: str):
        return (
            self.db.execute(
                text(
                    """
                    SELECT id, created_at
                    FROM sales_messages
                    WHERE tenant_id = :tenant_id
                      AND provider = 'web_widget'
                      AND external_id = :external_id
                    """
                ),
                {"tenant_id": tenant_id, "external_id": external_id},
            )
            .mappings()
            .first()
        )

    def _last_message_id(self, *, tenant_id: str, conversation_id: str):
        row = (
            self.db.execute(
                text(
                    """
                    SELECT id
                    FROM sales_messages
                    WHERE tenant_id = :tenant_id
                      AND conversation_id = :conversation_id
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": UUID(str(conversation_id)),
                },
            )
            .mappings()
            .first()
        )
        return row["id"] if row else None

    def _message_cursor(self, *, tenant_id: str, conversation_id: str, after: str | None):
        if not after or after == "0":
            return None
        try:
            message_id = UUID(str(after))
        except ValueError:
            return None
        return (
            self.db.execute(
                text(
                    """
                    SELECT id, created_at
                    FROM sales_messages
                    WHERE tenant_id = :tenant_id
                      AND conversation_id = :conversation_id
                      AND id = :message_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": UUID(str(conversation_id)),
                    "message_id": message_id,
                },
            )
            .mappings()
            .first()
        )

    def _lock_visitor(self, *, tenant_id: str, widget_id: str, visitor_id: str) -> None:
        self.db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": f"{tenant_id}:widget:{widget_id}:{visitor_id}"},
        )

    @staticmethod
    def _visitor_identifier(widget_id: str, visitor_id: str) -> str:
        return f"web:{widget_id}:{visitor_id}"[:160]

    @staticmethod
    def _rate_limit_ip_key(widget_id: str, client_ip: str) -> str:
        digest = hashlib.sha256(f"{widget_id}:{client_ip}".encode()).hexdigest()[:32]
        return f"widget:ip:{digest}"

    @staticmethod
    def _rate_limit_widget_key(widget_id: str) -> str:
        digest = hashlib.sha256(widget_id.encode()).hexdigest()[:32]
        return f"widget:global:{digest}"

    @staticmethod
    def _message_external_id(
        *,
        widget_id: str,
        visitor_id: str,
        client_message_id: str | None,
        message: str,
    ) -> str:
        cleaned_client_id = str(client_message_id or "").strip()
        if cleaned_client_id:
            digest = hashlib.sha256(cleaned_client_id.encode()).hexdigest()[:32]
        else:
            digest = hashlib.sha256(f"{visitor_id}:{message}".encode()).hexdigest()[:32]
        return f"widget:{widget_id}:visitor:{visitor_id}:message:{digest}"[:255]

    @staticmethod
    def _required_string(value: str | None, message: str) -> str:
        cleaned = str(value or "").strip()
        if not cleaned:
            raise HTTPException(status_code=400, detail=message)
        return cleaned

    @staticmethod
    def _optional_string(value: str | None) -> str | None:
        cleaned = str(value or "").strip()
        return cleaned or None

    @staticmethod
    def _json_object(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)


def build_widget_js(
    *,
    widget_id: str,
    color: str,
    greeting: str,
    position: str,
    name: str,
    api_origin: str,
) -> str:
    is_left = "left" in position.lower()
    horizontal = "left: 20px;" if is_left else "right: 20px;"
    safe = {
        "widget_id": json.dumps(widget_id),
        "api_origin": json.dumps(api_origin.rstrip("/")),
        "color": json.dumps(color),
        "greeting": json.dumps(greeting),
        "name": json.dumps(name),
    }
    return f"""(function() {{
  if (window.__labby_widget) return;
  window.__labby_widget = true;

  var WIDGET_ID = {safe["widget_id"]};
  var API_BASE = {safe["api_origin"]};
  var COLOR = {safe["color"]};
  var GREETING = {safe["greeting"]};
  var NAME = {safe["name"]};
  var VISITOR_ID = localStorage.getItem('labby_visitor_id');
  if (!VISITOR_ID) {{
    VISITOR_ID = 'v_' + Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
    localStorage.setItem('labby_visitor_id', VISITOR_ID);
  }}
  var visitorName = localStorage.getItem('labby_visitor_name') || '';
  var lastMessageId = localStorage.getItem('labby_' + WIDGET_ID + '_last_message_id') || '';
  var pollTimer = null;
  var open = false;

  var style = document.createElement('style');
  style.textContent = `
    #labby-widget-button {{
      position: fixed; bottom: 20px; {horizontal} width: 58px; height: 58px;
      border-radius: 50%; border: 0; background: ${{COLOR}}; color: #fff;
      display: flex; align-items: center; justify-content: center; cursor: pointer;
      box-shadow: 0 8px 28px rgba(0,0,0,.22); z-index: 2147483000;
      font: 500 24px/1 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    #labby-widget-panel {{
      position: fixed; bottom: 88px; {horizontal} width: 370px;
      max-width: calc(100vw - 32px); height: 520px; max-height: calc(100vh - 116px);
      background: #fff; color: #17202a; border-radius: 12px;
      box-shadow: 0 18px 54px rgba(0,0,0,.22); z-index: 2147483001;
      display: none; flex-direction: column; overflow: hidden;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    #labby-widget-panel.labby-open {{ display: flex; }}
    #labby-widget-header {{
      background: ${{COLOR}}; color: #fff; padding: 14px 16px;
      display: flex; align-items: center; justify-content: space-between;
      font-weight: 700;
    }}
    #labby-widget-close {{
      border: 0; background: transparent; color: #fff; font-size: 22px;
      cursor: pointer;
    }}
    #labby-widget-messages {{
      flex: 1; overflow-y: auto; padding: 14px; display: flex;
      flex-direction: column; gap: 8px;
    }}
    .labby-message {{
      max-width: 82%; padding: 9px 12px; border-radius: 12px;
      font-size: 14px; line-height: 1.4; word-break: break-word;
    }}
    .labby-message-in {{
      align-self: flex-start; background: #eef2f7; color: #17202a;
      border-bottom-left-radius: 4px;
    }}
    .labby-message-out {{
      align-self: flex-end; background: ${{COLOR}}; color: #fff;
      border-bottom-right-radius: 4px;
    }}
    #labby-widget-greeting {{
      color: #667085; font-size: 13px; text-align: center; padding: 6px 12px;
    }}
    #labby-widget-name, #labby-widget-compose {{
      border-top: 1px solid #e5e7eb; padding: 12px; display: flex; gap: 8px;
    }}
    #labby-widget-name input, #labby-widget-compose input {{
      flex: 1; min-width: 0; border: 1px solid #d0d5dd; border-radius: 8px;
      padding: 10px 12px; font-size: 14px;
    }}
    #labby-widget-name button, #labby-widget-compose button {{
      border: 0; border-radius: 8px; background: ${{COLOR}}; color: #fff;
      padding: 0 14px; cursor: pointer; font-weight: 700;
    }}
    @media (max-width: 480px) {{
      #labby-widget-panel {{
        right: 8px !important; left: 8px !important;
        width: auto; height: calc(100vh - 104px);
      }}
    }}
  `;
  document.head.appendChild(style);

  var button = document.createElement('button');
  button.id = 'labby-widget-button';
  button.setAttribute('aria-label', 'Abrir chat');
  button.textContent = 'Chat';
  document.body.appendChild(button);

  var panel = document.createElement('div');
  panel.id = 'labby-widget-panel';
  panel.innerHTML =
    '<div id="labby-widget-header"><span>' + escapeHtml(NAME) + '</span>' +
    '<button id="labby-widget-close" aria-label="Fechar">&times;</button></div>' +
    '<div id="labby-widget-messages"><div id="labby-widget-greeting">' +
    escapeHtml(GREETING) + '</div></div>' +
    '<div id="labby-widget-name"><input maxlength="180" ' +
    'placeholder="Seu nome..." /><button>Iniciar</button></div>' +
    '<div id="labby-widget-compose" style="display:none"><input maxlength="4000" ' +
    'placeholder="Digite sua mensagem..." /><button>Enviar</button></div>';
  document.body.appendChild(panel);

  var messages = document.getElementById('labby-widget-messages');
  var nameBox = document.getElementById('labby-widget-name');
  var nameInput = nameBox.querySelector('input');
  var nameButton = nameBox.querySelector('button');
  var compose = document.getElementById('labby-widget-compose');
  var input = compose.querySelector('input');
  var sendButton = compose.querySelector('button');

  function escapeHtml(value) {{
    return String(value || '').replace(/[&<>"']/g, function(ch) {{
      return {{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[ch];
    }});
  }}
  function addMessage(text, direction) {{
    var div = document.createElement('div');
    div.className = 'labby-message ' +
      (direction === 'saida' ? 'labby-message-in' : 'labby-message-out');
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }}
  function ensureNamed() {{
    if (visitorName) {{
      nameBox.style.display = 'none';
      compose.style.display = 'flex';
      input.focus();
      poll();
      startPolling();
    }} else {{
      nameBox.style.display = 'flex';
      compose.style.display = 'none';
      nameInput.focus();
    }}
  }}
  function setLast(id) {{
    if (!id) return;
    lastMessageId = id;
    localStorage.setItem('labby_' + WIDGET_ID + '_last_message_id', id);
  }}
  function startPolling() {{
    if (pollTimer) return;
    pollTimer = setInterval(poll, 3000);
  }}
  function stopPolling() {{
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }}
  function poll() {{
    var url = API_BASE + '/widget/' + encodeURIComponent(WIDGET_ID) + '/messages?visitor_id=' +
      encodeURIComponent(VISITOR_ID) +
      (lastMessageId ? '&after=' + encodeURIComponent(lastMessageId) : '');
    fetch(url).then(function(r) {{
      return r.ok ? r.json() : {{messages: []}};
    }}).then(function(data) {{
      (data.messages || []).forEach(function(m) {{
        setLast(m.id);
        if (m.direction === 'saida') addMessage(m.content, 'saida');
      }});
    }}).catch(function() {{}});
  }}
  function send() {{
    var text = input.value.trim();
    if (!text) return;
    input.value = '';
    sendButton.disabled = true;
    addMessage(text, 'entrada');
    var clientMessageId = 'm_' + Date.now().toString(36) + '_' +
      Math.random().toString(36).slice(2, 10);
    fetch(API_BASE + '/widget/' + encodeURIComponent(WIDGET_ID) + '/messages', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        visitor_id: VISITOR_ID,
        visitor_name: visitorName,
        message: text,
        client_message_id: clientMessageId
      }})
    }}).then(function(r) {{
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    }}).then(function(data) {{
      setLast(data.last_message_id);
      if (data.bot_response) addMessage(data.bot_response, 'saida');
      sendButton.disabled = false;
    }}).catch(function() {{
      addMessage('Erro ao enviar. Tente novamente.', 'saida');
      sendButton.disabled = false;
    }});
  }}

  button.addEventListener('click', function() {{
    open = !open;
    panel.classList.toggle('labby-open', open);
    if (open) ensureNamed(); else stopPolling();
  }});
  document.getElementById('labby-widget-close').addEventListener('click', function() {{
    open = false;
    panel.classList.remove('labby-open');
    stopPolling();
  }});
  nameButton.addEventListener('click', function() {{
    var value = nameInput.value.trim();
    if (!value) return;
    visitorName = value;
    localStorage.setItem('labby_visitor_name', visitorName);
    ensureNamed();
  }});
  nameInput.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter') nameButton.click();
  }});
  sendButton.addEventListener('click', send);
  input.addEventListener('keydown', function(e) {{
    if (e.key === 'Enter' && !e.shiftKey) {{
      e.preventDefault();
      send();
    }}
  }});
}})();"""
