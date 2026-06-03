import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.domains.jobs.registry import JobExecutionContext, PermanentJobError, job_handlers
from app.domains.sales.contact_service import normalize_phone
from app.domains.sales.webhook_service import SALES_EVOLUTION_WEBHOOK_JOB


@job_handlers.register(SALES_EVOLUTION_WEBHOOK_JOB)
def process_sales_evolution_webhook(context: JobExecutionContext) -> dict[str, Any]:
    with SessionLocal() as db:
        return SalesWebhookJobProcessor(db).process_evolution(context)


class SalesWebhookJobProcessor:
    def __init__(self, db: Session) -> None:
        self.db = db

    def process_evolution(self, context: JobExecutionContext) -> dict[str, Any]:
        webhook_event_id = str(context.payload.get("webhook_event_id") or "")
        channel_id = str(context.payload.get("channel_id") or "")
        if not webhook_event_id or not channel_id:
            raise PermanentJobError("Payload sem webhook_event_id ou channel_id")

        event = self._load_event(context.tenant_id, webhook_event_id)
        if event["status"] in {"processed", "ignored"}:
            return {
                "webhook_event_id": webhook_event_id,
                "skipped": True,
                "status": event["status"],
            }

        raw_payload = dict((event["payload"] or {}).get("raw") or {})
        event_type = str(event["event_type"] or "").lower()
        self._mark_event_processing(webhook_event_id)

        if event_type == "connection.update":
            result = self._process_connection_update(
                tenant_id=context.tenant_id,
                channel_id=channel_id,
                payload=raw_payload,
            )
        elif event_type == "qrcode.updated":
            result = self._process_qrcode_update(
                tenant_id=context.tenant_id,
                channel_id=channel_id,
                payload=raw_payload,
            )
        elif event_type == "messages.update":
            result = self._process_message_status_update(
                tenant_id=context.tenant_id,
                payload=raw_payload,
            )
        elif event_type == "messages.upsert":
            result = self._process_message_upsert(
                tenant_id=context.tenant_id,
                channel_id=channel_id,
                payload=raw_payload,
            )
        else:
            self._finish_event(webhook_event_id, "ignored")
            self.db.commit()
            return {"webhook_event_id": webhook_event_id, "ignored": True, "event_type": event_type}

        self._finish_event(webhook_event_id, "processed")
        self.db.commit()
        return {"webhook_event_id": webhook_event_id, "event_type": event_type, **result}

    def _process_connection_update(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = _payload_data(payload)
        state = str(data.get("state") or "").lower()
        status = {
            "open": "conectado",
            "close": "desconectado",
            "connecting": "conectando",
        }.get(state)
        if not status:
            return {"updated": False, "state": state}

        self.db.execute(
            text(
                """
                UPDATE sales_channels
                SET status = :status,
                    last_event_at = NOW(),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :channel_id
                """
            ),
            {"tenant_id": tenant_id, "channel_id": channel_id, "status": status},
        )
        return {"updated": True, "state": state, "channel_status": status}

    def _process_qrcode_update(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = _payload_data(payload)
        qrcode = data.get("qrcode")
        qr_base64 = ""
        if isinstance(qrcode, dict):
            qr_base64 = str(qrcode.get("base64") or "")
        elif qrcode:
            qr_base64 = str(qrcode)

        if qr_base64:
            self.db.execute(
                text(
                    """
                    UPDATE sales_channels
                    SET config = config || CAST(:config AS jsonb),
                        last_event_at = NOW(),
                        updated_at = NOW()
                    WHERE tenant_id = :tenant_id
                      AND id = :channel_id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "channel_id": channel_id,
                    "config": _json({"last_qr_code": qr_base64}),
                },
            )
        return {"qr_updated": bool(qr_base64)}

    def _process_message_status_update(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        data = payload.get("data")
        updates = data if isinstance(data, list) else [data]
        status_map = {
            "delivery_ack": "delivered",
            "read": "read",
            "played": "read",
            "server_ack": "sent",
        }
        updated = 0
        for update in updates:
            if not isinstance(update, dict):
                continue
            key = update.get("key") if isinstance(update.get("key"), dict) else {}
            external_id = str(key.get("id") or update.get("id") or "").strip()
            raw_status = str(update.get("status") or "").strip().lower()
            status = status_map.get(raw_status)
            if not external_id or not status:
                continue
            result = self.db.execute(
                text(
                    """
                    UPDATE sales_messages
                    SET status = :status
                    WHERE tenant_id = :tenant_id
                      AND (
                            (provider = 'evolution' AND external_id = :external_id)
                            OR (
                                delivery_provider = 'evolution'
                                AND delivery_external_id = :external_id
                            )
                      )
                    """
                ),
                {"tenant_id": tenant_id, "external_id": external_id, "status": status},
            )
            updated += int(result.rowcount or 0)
        return {"message_status_updates": updated}

    def _process_message_upsert(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        message = _parse_evolution_message(payload)
        if message.ignored_reason:
            return {"ignored": True, "reason": message.ignored_reason}

        contact_id = self._find_or_create_contact(tenant_id, channel_id, message)
        conversation_id = self._find_or_create_conversation(tenant_id, channel_id, contact_id)
        inserted = self._insert_message(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            message=message,
        )
        if not inserted:
            return {
                "contact_id": contact_id,
                "conversation_id": conversation_id,
                "message_inserted": False,
            }

        created_at = inserted["created_at"]
        self.db.execute(
            text(
                """
                UPDATE sales_conversations
                SET status = CASE WHEN status = 'fechada' THEN 'aberta' ELSE status END,
                    waiting_for_human = true,
                    last_message_at = :created_at,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :conversation_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
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
            {"tenant_id": tenant_id, "contact_id": contact_id, "created_at": created_at},
        )
        self.db.execute(
            text(
                """
                UPDATE sales_channels
                SET last_event_at = :created_at,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :channel_id
                """
            ),
            {"tenant_id": tenant_id, "channel_id": channel_id, "created_at": created_at},
        )
        return {
            "contact_id": contact_id,
            "conversation_id": conversation_id,
            "message_id": str(inserted["id"]),
            "message_inserted": True,
        }

    def _find_or_create_contact(
        self,
        tenant_id: str,
        channel_id: str,
        message: "EvolutionMessage",
    ) -> str:
        existing_channel = (
            self.db.execute(
                text(
                    """
                    SELECT contact_id
                    FROM sales_contact_channels
                    WHERE tenant_id = :tenant_id
                      AND channel_type = 'whatsapp_evolution'
                      AND identifier = :identifier
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "identifier": message.identifier},
            )
            .mappings()
            .first()
        )
        if existing_channel:
            contact_id = str(existing_channel["contact_id"])
        else:
            contact_id = self._upsert_contact_by_phone(tenant_id, message)

        self.db.execute(
            text(
                """
                INSERT INTO sales_contact_channels (
                    tenant_id, contact_id, channel_id, channel_type, identifier, metadata
                )
                VALUES (
                    :tenant_id, :contact_id, :channel_id, 'whatsapp_evolution',
                    :identifier, CAST(:metadata AS jsonb)
                )
                ON CONFLICT (tenant_id, channel_type, identifier)
                DO UPDATE SET
                    contact_id = EXCLUDED.contact_id,
                    channel_id = EXCLUDED.channel_id,
                    metadata = sales_contact_channels.metadata || EXCLUDED.metadata
                """
            ),
            {
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "channel_id": channel_id,
                "identifier": message.identifier,
                "metadata": _json(
                    {
                        "remote_jid": message.remote_jid,
                        "push_name": message.push_name,
                    }
                ),
            },
        )
        return contact_id

    def _upsert_contact_by_phone(self, tenant_id: str, message: "EvolutionMessage") -> str:
        row = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_contacts (
                        tenant_id, name, phone, phone_normalized, tags, custom_fields
                    )
                    VALUES (
                        :tenant_id, :name, :phone, :phone_normalized,
                        '["whatsapp"]'::jsonb, CAST(:custom_fields AS jsonb)
                    )
                    ON CONFLICT (tenant_id, phone_normalized)
                        WHERE phone_normalized IS NOT NULL
                    DO UPDATE SET
                        name = CASE
                            WHEN sales_contacts.name = sales_contacts.phone
                              OR sales_contacts.name = 'Sem nome'
                            THEN EXCLUDED.name
                            ELSE sales_contacts.name
                        END,
                        custom_fields = sales_contacts.custom_fields || EXCLUDED.custom_fields,
                        updated_at = NOW()
                    RETURNING id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "name": message.push_name or message.phone or "Sem nome",
                    "phone": message.phone,
                    "phone_normalized": message.phone_normalized,
                    "custom_fields": _json(
                        {
                            "whatsapp_remote_jid": message.remote_jid,
                        }
                    ),
                },
            )
            .mappings()
            .one()
        )
        return str(row["id"])

    def _find_or_create_conversation(
        self,
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
                    ORDER BY last_message_at DESC NULLS LAST, created_at DESC, id DESC
                    FOR UPDATE
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "contact_id": contact_id,
                    "channel_id": channel_id,
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
                    "contact_id": contact_id,
                    "channel_id": channel_id,
                },
            )
            .mappings()
            .one()
        )
        return str(row["id"])

    def _insert_message(
        self,
        *,
        tenant_id: str,
        conversation_id: str,
        contact_id: str,
        message: "EvolutionMessage",
    ):
        return (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_messages (
                        tenant_id, conversation_id, contact_id, direction,
                        sender_type, message_type, content, media_url,
                        media_caption, provider, external_id, status, metadata
                    )
                    VALUES (
                        :tenant_id, :conversation_id, :contact_id, 'entrada',
                        'contato', :message_type, :content, :media_url,
                        :media_caption, 'evolution', :external_id, 'sent',
                        CAST(:metadata AS jsonb)
                    )
                    ON CONFLICT (tenant_id, provider, external_id)
                        WHERE provider IS NOT NULL AND external_id IS NOT NULL
                    DO NOTHING
                    RETURNING id, created_at
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "conversation_id": conversation_id,
                    "contact_id": contact_id,
                    "message_type": message.message_type,
                    "content": message.content,
                    "media_url": message.media_url,
                    "media_caption": message.media_caption,
                    "external_id": message.external_id,
                    "metadata": _json(
                        {
                            "remote_jid": message.remote_jid,
                            "message_kind": message.message_kind,
                        }
                    ),
                },
            )
            .mappings()
            .first()
        )

    def _load_event(self, tenant_id: str, webhook_event_id: str) -> dict[str, Any]:
        row = (
            self.db.execute(
                text(
                    """
                    SELECT *
                    FROM webhook_events
                    WHERE tenant_id = :tenant_id
                      AND id = :webhook_event_id
                    FOR UPDATE
                    """
                ),
                {"tenant_id": tenant_id, "webhook_event_id": webhook_event_id},
            )
            .mappings()
            .first()
        )
        if not row:
            raise PermanentJobError("Webhook event nao encontrado")
        return dict(row)

    def _mark_event_processing(self, webhook_event_id: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE webhook_events
                SET status = 'processing',
                    updated_at = NOW()
                WHERE id = :webhook_event_id
                """
            ),
            {"webhook_event_id": webhook_event_id},
        )

    def _finish_event(self, webhook_event_id: str, status: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE webhook_events
                SET status = :status,
                    processed_at = CASE
                        WHEN :status IN ('processed', 'ignored') THEN NOW()
                        ELSE processed_at
                    END,
                    updated_at = NOW()
                WHERE id = :webhook_event_id
                """
            ),
            {"webhook_event_id": webhook_event_id, "status": status},
        )


@dataclass(frozen=True)
class EvolutionMessage:
    external_id: str
    remote_jid: str
    identifier: str
    phone: str | None
    phone_normalized: str | None
    push_name: str | None
    content: str
    message_type: str
    message_kind: str
    media_url: str | None = None
    media_caption: str | None = None
    ignored_reason: str | None = None


def _parse_evolution_message(payload: dict[str, Any]) -> EvolutionMessage:
    data = _payload_data(payload)
    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    remote_jid = str(key.get("remoteJid") or data.get("remoteJid") or "").strip()
    external_id = str(key.get("id") or data.get("id") or "").strip()
    if not external_id:
        external_id = _fallback_message_external_id(payload)

    if key.get("fromMe") is True:
        return _ignored_message(external_id, remote_jid, "from_me")
    if not remote_jid:
        return _ignored_message(external_id, remote_jid, "missing_remote_jid")
    if "@g.us" in remote_jid or remote_jid == "status@broadcast":
        return _ignored_message(external_id, remote_jid, "unsupported_chat")

    phone = remote_jid.replace("@s.whatsapp.net", "").replace("@c.us", "").strip()
    phone = phone.replace("@lid", "").strip()
    phone_normalized = normalize_phone(phone)
    message_obj = data.get("message") if isinstance(data.get("message"), dict) else {}
    content, message_type, message_kind, media_caption = _extract_message_content(message_obj)
    push_name = str(data.get("pushName") or data.get("senderName") or phone or "").strip() or None

    return EvolutionMessage(
        external_id=external_id,
        remote_jid=remote_jid,
        identifier=remote_jid or phone or external_id,
        phone=phone or None,
        phone_normalized=phone_normalized,
        push_name=push_name,
        content=content,
        message_type=message_type,
        message_kind=message_kind,
        media_caption=media_caption,
    )


def _payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else {}
    return data if isinstance(data, dict) else {}


def _extract_message_content(message_obj: dict[str, Any]) -> tuple[str, str, str, str | None]:
    if message_obj.get("conversation"):
        return str(message_obj["conversation"]), "text", "conversation", None

    extended = message_obj.get("extendedTextMessage")
    if isinstance(extended, dict) and extended.get("text"):
        return str(extended["text"]), "text", "extendedTextMessage", None

    image = message_obj.get("imageMessage")
    if isinstance(image, dict):
        caption = str(image.get("caption") or "")
        return caption or "[Imagem]", "image", "imageMessage", caption or None

    video = message_obj.get("videoMessage")
    if isinstance(video, dict):
        caption = str(video.get("caption") or "")
        return caption or "[Video]", "video", "videoMessage", caption or None

    document = message_obj.get("documentMessage")
    if isinstance(document, dict):
        filename = str(document.get("fileName") or "")
        return filename or "[Documento]", "document", "documentMessage", filename or None

    if message_obj.get("audioMessage"):
        return "[Audio]", "text", "audioMessage", None

    if message_obj.get("stickerMessage"):
        return "[Sticker]", "text", "stickerMessage", None

    return "[Mensagem]", "text", "unknown", None


def _ignored_message(external_id: str, remote_jid: str, reason: str) -> EvolutionMessage:
    return EvolutionMessage(
        external_id=external_id or _fallback_message_external_id({"remote_jid": remote_jid}),
        remote_jid=remote_jid,
        identifier=remote_jid or external_id or "unknown",
        phone=None,
        phone_normalized=None,
        push_name=None,
        content="",
        message_type="text",
        message_kind="ignored",
        ignored_reason=reason,
    )


def _fallback_message_external_id(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f"hash:{digest[:48]}"


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)
