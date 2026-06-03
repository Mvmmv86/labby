import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domains.jobs.job_service import JobQueueService

SALES_EVOLUTION_WEBHOOK_JOB = "sales.webhook.evolution"
SALES_WEBHOOK_QUEUE = "worker-sales-webhooks"
EVOLUTION_CHANNEL_LIFECYCLE_EVENTS = {"connection.update", "qrcode.updated"}
EVOLUTION_WEBHOOK_LIMIT_PER_CHANNEL_PER_MINUTE = 600

SECRET_HEADER_NAMES = {
    "authorization",
    "x-api-key",
    "x-evolution-token",
    "x-labby-webhook-secret",
    "x-omniaflow-webhook-secret",
}


class SalesWebhookReceiver:
    def __init__(self, db: Session, *, job_queue: JobQueueService | None = None) -> None:
        self.db = db
        self.job_queue = job_queue or JobQueueService(db)

    def receive_evolution(
        self,
        *,
        channel_id: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        client_ip: str = "unknown",
    ) -> dict[str, Any]:
        channel = self._get_public_channel(channel_id)
        if channel is None:
            return {"status": "channel_not_found", "duplicate": False}

        if channel["channel_type"] != "whatsapp_evolution":
            raise HTTPException(status_code=404, detail="Canal Evolution nao encontrado")

        self._validate_secret(
            expected=str(channel["webhook_secret"] or ""),
            headers=headers,
        )
        self._enforce_webhook_rate_limit(
            tenant_id=str(channel["tenant_id"]),
            channel_id=channel_id,
            client_ip=client_ip,
        )

        event_type = _normalize_event_type(payload.get("event") or "unknown")
        external_event_id = _extract_evolution_external_id(payload)
        idempotency_key = _event_idempotency_key(
            channel_id=channel_id,
            event_type=event_type,
            external_event_id=external_event_id,
            payload=payload,
        )
        duplicate = self._webhook_event_exists(
            tenant_id=str(channel["tenant_id"]),
            provider="evolution",
            idempotency_key=idempotency_key,
        )
        if (
            str(channel["status"]) != "conectado"
            and event_type not in EVOLUTION_CHANNEL_LIFECYCLE_EVENTS
        ):
            event_id = self._record_ignored_evolution_event(
                channel_id=channel_id,
                tenant_id=str(channel["tenant_id"]),
                event_type=event_type,
                external_event_id=external_event_id,
                idempotency_key=idempotency_key,
                headers=headers,
                payload=payload,
            )
            return {
                "status": "ignored",
                "webhook_event_id": UUID(str(event_id)),
                "job_id": None,
                "duplicate": duplicate,
            }

        event_id = self.job_queue.record_webhook_event(
            tenant_id=str(channel["tenant_id"]),
            provider="evolution",
            external_event_id=external_event_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            signature_valid=True,
            headers=_safe_headers(headers),
            payload={
                "channel_id": channel_id,
                "raw": payload,
            },
            commit=False,
        )
        job = self.job_queue.enqueue_job(
            tenant_id=str(channel["tenant_id"]),
            job_type=SALES_EVOLUTION_WEBHOOK_JOB,
            queue_name=SALES_WEBHOOK_QUEUE,
            idempotency_key=idempotency_key,
            payload={
                "webhook_event_id": event_id,
                "channel_id": channel_id,
                "event_type": event_type,
            },
            commit=False,
        )
        self.db.execute(
            text(
                """
                UPDATE webhook_events
                SET job_id = :job_id,
                    updated_at = NOW()
                WHERE id = :event_id
                """
            ),
            {"job_id": job.id, "event_id": event_id},
        )
        self.db.commit()
        return {
            "status": "queued",
            "webhook_event_id": UUID(str(event_id)),
            "job_id": UUID(str(job.id)),
            "duplicate": duplicate,
        }

    def _get_public_channel(self, channel_id: str):
        try:
            channel_uuid = UUID(str(channel_id))
        except ValueError:
            return None
        return (
            self.db.execute(
                text(
                    """
                    SELECT id, tenant_id, channel_type, status, webhook_secret
                    FROM sales_channels
                    WHERE id = :channel_id
                    """
                ),
                {"channel_id": channel_uuid},
            )
            .mappings()
            .first()
        )

    def _record_ignored_evolution_event(
        self,
        *,
        channel_id: str,
        tenant_id: str,
        event_type: str,
        external_event_id: str | None,
        idempotency_key: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> str:
        event_id = self.job_queue.record_webhook_event(
            tenant_id=tenant_id,
            provider="evolution",
            external_event_id=external_event_id,
            event_type=event_type,
            idempotency_key=idempotency_key,
            signature_valid=True,
            headers=_safe_headers(headers),
            payload={
                "channel_id": channel_id,
                "raw": payload,
            },
            commit=False,
        )
        self.db.execute(
            text(
                """
                UPDATE webhook_events
                SET status = 'ignored',
                    processed_at = NOW(),
                    error_code = 'channel_not_connected',
                    error_message = 'Channel is not connected',
                    updated_at = NOW()
                WHERE id = :event_id
                  AND status = 'received'
                """
            ),
            {"event_id": event_id},
        )
        self.db.commit()
        return str(event_id)

    def _webhook_event_exists(
        self,
        *,
        tenant_id: str,
        provider: str,
        idempotency_key: str,
    ) -> bool:
        return (
            self.db.execute(
                text(
                    """
                    SELECT 1
                    FROM webhook_events
                    WHERE tenant_id = :tenant_id
                      AND provider = :provider
                      AND idempotency_key = :idempotency_key
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "provider": provider,
                    "idempotency_key": idempotency_key,
                },
            ).first()
            is not None
        )

    def _enforce_webhook_rate_limit(
        self,
        *,
        tenant_id: str,
        channel_id: str,
        client_ip: str,
    ) -> None:
        self._enforce_rate_limit(
            tenant_id=tenant_id,
            key=_rate_limit_key("channel", channel_id),
            action="webhook.evolution.channel",
            limit=EVOLUTION_WEBHOOK_LIMIT_PER_CHANNEL_PER_MINUTE,
            metadata={
                "channel_id": channel_id,
                "client_ip": client_ip,
                "scope": "channel",
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
                  AND provider = 'evolution'
                  AND rate_limit_key = :rate_limit_key
                  AND action = :action
                  AND outcome = 'allowed'
                  AND created_at >= NOW() - INTERVAL '60 seconds'
                """
            ),
            {
                "tenant_id": tenant_id,
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
                    :tenant_id, 'evolution', :rate_limit_key, :action, :outcome,
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
                "rate_limit_key": key,
                "action": action,
                "outcome": outcome,
                "metadata": json.dumps(metadata, ensure_ascii=False),
            },
        )
        self.db.commit()
        if outcome == "blocked":
            raise HTTPException(status_code=429, detail="Limite de webhook excedido")

    @staticmethod
    def _validate_secret(*, expected: str, headers: dict[str, str]) -> None:
        expected = str(expected or "").strip()
        if not expected:
            raise HTTPException(status_code=401, detail="Webhook secret nao configurado")
        received = (
            headers.get("x-labby-webhook-secret")
            or headers.get("x-omniaflow-webhook-secret")
            or headers.get("x-evolution-token")
            or ""
        )
        if not hmac.compare_digest(str(received).strip(), expected):
            raise HTTPException(status_code=401, detail="Webhook signature invalida")


def _safe_headers(headers: dict[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        safe[lower] = "***" if lower in SECRET_HEADER_NAMES else str(value)
    return safe


def _normalize_event_type(value: Any) -> str:
    return str(value or "unknown").strip().lower().replace("_", ".")


def _extract_evolution_external_id(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return None

    key = data.get("key")
    if isinstance(key, dict) and key.get("id"):
        return str(key["id"])

    if data.get("id"):
        return str(data["id"])

    message = data.get("message")
    if isinstance(message, dict):
        message_key = message.get("key")
        if isinstance(message_key, dict) and message_key.get("id"):
            return str(message_key["id"])

    return None


def _event_idempotency_key(
    *,
    channel_id: str,
    event_type: str,
    external_event_id: str | None,
    payload: dict[str, Any],
) -> str:
    if external_event_id:
        digest = hashlib.sha256(external_event_id.encode("utf-8")).hexdigest()[:32]
        return f"evolution:{channel_id}:{event_type}:{digest}"

    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:32]
    return f"evolution:{channel_id}:{event_type}:{payload_hash}"


def _rate_limit_key(scope: str, channel_id: str) -> str:
    digest = hashlib.sha256(f"{scope}:{channel_id}".encode()).hexdigest()
    return f"evolution:webhook:{scope}:{digest[:32]}"
