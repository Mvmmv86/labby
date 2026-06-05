import asyncio
import json
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.domains.jobs.registry import (
    JobExecutionContext,
    PermanentJobError,
    RetryableJobError,
    job_handlers,
)
from app.domains.sales.outbound_service import SALES_MESSAGE_DISPATCH_JOB
from app.integrations.sales_channels import (
    EvolutionOutboundAdapter,
    OutboundDeliveryUnknown,
    OutboundProviderError,
    OutboundReconcileResult,
    OutboundReconciliationUnavailable,
    OutboundSendResult,
)


class SalesOutboundAdapter(Protocol):
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
        ...

    async def reconcile_message(
        self,
        *,
        channel_config: dict[str, Any],
        recipient_identifier: str,
        content: str | None,
        media_url: str | None,
        idempotency_key: str,
    ) -> OutboundReconcileResult | None:
        ...


@job_handlers.register(SALES_MESSAGE_DISPATCH_JOB)
def dispatch_sales_message(context: JobExecutionContext) -> dict[str, Any]:
    with SessionLocal() as db:
        adapter = EvolutionOutboundAdapter(get_settings())
        return SalesOutboundJobProcessor(db, evolution_adapter=adapter).dispatch(context)


class SalesOutboundJobProcessor:
    def __init__(
        self,
        db: Session,
        *,
        evolution_adapter: SalesOutboundAdapter | None = None,
        reconciliation_grace_seconds: int | None = None,
    ) -> None:
        self.db = db
        settings = get_settings()
        self.evolution_adapter = evolution_adapter or EvolutionOutboundAdapter(settings)
        self.reconciliation_grace_seconds = (
            settings.sales_outbound_reconciliation_grace_seconds
            if reconciliation_grace_seconds is None
            else max(0, reconciliation_grace_seconds)
        )

    def dispatch(self, context: JobExecutionContext) -> dict[str, Any]:
        message_id = str(context.payload.get("message_id") or "")
        if not message_id:
            raise PermanentJobError("Payload sem message_id")

        message = self._load_message(context.tenant_id, message_id)
        if message["direction"] != "saida":
            raise PermanentJobError("Mensagem nao e de saida")

        if message["delivery_external_id"] or message["status"] in {"sent", "delivered", "read"}:
            return {
                "message_id": message_id,
                "skipped": True,
                "status": message["status"],
                "delivery_external_id": message["delivery_external_id"],
            }

        if message["status"] == "failed":
            raise PermanentJobError("Mensagem ja esta marcada como failed")

        if message["channel_type"] != "whatsapp_evolution":
            self._mark_message_failed(
                tenant_id=context.tenant_id,
                message_id=message_id,
                error=f"Canal sem outbound implementado: {message['channel_type']}",
            )
            self.db.commit()
            raise PermanentJobError("Outbound implementado apenas para Evolution")

        if message["channel_status"] != "conectado":
            self._mark_message_failed(
                tenant_id=context.tenant_id,
                message_id=message_id,
                error="Canal nao conectado",
            )
            self.db.commit()
            raise PermanentJobError("Canal nao conectado")

        recipient_identifier = str(message["recipient_identifier"] or "").strip()
        if not recipient_identifier:
            self._mark_message_failed(
                tenant_id=context.tenant_id,
                message_id=message_id,
                error="Contato sem identificador para o canal",
            )
            self.db.commit()
            raise PermanentJobError("Contato sem identificador para o canal")

        if message["status"] == "sending":
            attempt = self._load_attempt_for_message(
                tenant_id=context.tenant_id,
                message_id=message_id,
            )
            if attempt is None:
                self._mark_message_failed(
                    tenant_id=context.tenant_id,
                    message_id=message_id,
                    error=(
                        "Mensagem estava em sending sem ledger de dispatch. "
                        "Reconciliacao manual necessaria para evitar double-send."
                    ),
                )
                self.db.commit()
                raise PermanentJobError("Mensagem em sending exige reconciliacao manual")
            reconciliation = self._reconcile_sending_message(
                context=context,
                message=message,
                attempt=attempt,
                recipient_identifier=recipient_identifier,
            )
            if reconciliation is not None:
                return reconciliation
        else:
            attempt = self._create_or_load_attempt(
                tenant_id=context.tenant_id,
                message=message,
            )

        if attempt["status"] == "sent" and attempt["provider_external_id"]:
            self._mark_message_sent(
                tenant_id=context.tenant_id,
                message_id=message_id,
                provider="evolution",
                external_id=str(attempt["provider_external_id"]),
                response=dict(attempt["response_payload"] or {}),
            )
            self.db.commit()
            return {
                "message_id": message_id,
                "skipped": True,
                "delivery_external_id": str(attempt["provider_external_id"]),
            }
        if attempt["status"] == "failed":
            raise PermanentJobError("Tentativa de envio ja falhou; recrie o dispatch manualmente")
        if attempt["status"] == "sending" and message["status"] not in {"pending", "sending"}:
            raise PermanentJobError("Tentativa em andamento exige reconciliacao manual")

        self._mark_message_sending(context.tenant_id, message_id)
        self.db.commit()

        request_payload = {
            "recipient_identifier": recipient_identifier,
            "message_type": str(message["message_type"]),
            "content": message["content"],
            "media_url": message["media_url"],
            "media_caption": message["media_caption"],
            "idempotency_key": str(attempt["idempotency_key"]),
        }
        self._mark_attempt_request(
            attempt_id=str(attempt["id"]),
            request_payload=request_payload,
        )
        self.db.commit()

        try:
            result = asyncio.run(
                self.evolution_adapter.send_message(
                    channel_config=dict(message["channel_config"] or {}),
                    recipient_identifier=recipient_identifier,
                    message_type=str(message["message_type"]),
                    content=message["content"],
                    media_url=message["media_url"],
                    media_caption=message["media_caption"],
                    idempotency_key=str(attempt["idempotency_key"]),
                )
            )
        except OutboundDeliveryUnknown as exc:
            self._mark_attempt_unknown(str(attempt["id"]), exc.__class__.__name__, str(exc))
            self._mark_message_unknown(context.tenant_id, message_id, str(exc))
            self.db.commit()
            raise RetryableJobError(str(exc)) from exc
        except OutboundProviderError as exc:
            self._mark_attempt_failed(str(attempt["id"]), exc.__class__.__name__, str(exc))
            self._mark_message_failed(context.tenant_id, message_id, str(exc))
            self._mark_campaign_recipient_failed(message_id=message_id, error=str(exc))
            self.db.commit()
            raise PermanentJobError(str(exc)) from exc

        self._mark_attempt_sent(
            attempt_id=str(attempt["id"]),
            provider_external_id=result.external_id,
            response_payload=result.response,
        )
        self._mark_message_sent(
            tenant_id=context.tenant_id,
            message_id=message_id,
            provider=result.provider,
            external_id=result.external_id,
            response=result.response,
        )
        self._mark_campaign_recipient_sent(message_id=message_id)
        self.db.commit()
        return {
            "message_id": message_id,
            "provider": result.provider,
            "delivery_external_id": result.external_id,
        }

    def _load_message(self, tenant_id: str, message_id: str) -> dict[str, Any]:
        row = (
            self.db.execute(
                text(
                    """
                    SELECT
                        m.*,
                        conv.channel_id,
                        ch.channel_type,
                        ch.status AS channel_status,
                        ch.config AS channel_config,
                        COALESCE(cc.identifier, c.phone_normalized, c.phone) AS recipient_identifier
                    FROM sales_messages m
                    JOIN sales_conversations conv
                      ON conv.id = m.conversation_id
                     AND conv.tenant_id = m.tenant_id
                    LEFT JOIN sales_channels ch
                      ON ch.id = conv.channel_id
                     AND ch.tenant_id = m.tenant_id
                    LEFT JOIN sales_contacts c
                      ON c.id = m.contact_id
                     AND c.tenant_id = m.tenant_id
                    LEFT JOIN sales_contact_channels cc
                      ON cc.tenant_id = m.tenant_id
                     AND cc.contact_id = m.contact_id
                     AND cc.channel_id = conv.channel_id
                    WHERE m.tenant_id = :tenant_id
                      AND m.id = :message_id
                    FOR UPDATE OF m
                    """
                ),
                {"tenant_id": tenant_id, "message_id": message_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise PermanentJobError("Mensagem nao encontrada")
        return dict(row)

    def _load_attempt_for_message(self, *, tenant_id: str, message_id: str):
        return (
            self.db.execute(
                text(
                    """
                    SELECT *
                    FROM sales_message_dispatch_attempts
                    WHERE tenant_id = :tenant_id
                      AND message_id = :message_id
                      AND provider = 'evolution'
                    ORDER BY created_at DESC
                    LIMIT 1
                    FOR UPDATE
                    """
                ),
                {"tenant_id": tenant_id, "message_id": message_id},
            )
            .mappings()
            .first()
        )

    def _reconcile_sending_message(
        self,
        *,
        context: JobExecutionContext,
        message: dict[str, Any],
        attempt,
        recipient_identifier: str,
    ) -> dict[str, Any] | None:
        try:
            result = asyncio.run(
                self.evolution_adapter.reconcile_message(
                    channel_config=dict(message["channel_config"] or {}),
                    recipient_identifier=recipient_identifier,
                    content=message["content"],
                    media_url=message["media_url"],
                    idempotency_key=str(attempt["idempotency_key"]),
                )
            )
        except OutboundReconciliationUnavailable as exc:
            self._mark_attempt_unknown(str(attempt["id"]), exc.__class__.__name__, str(exc))
            self._mark_message_unknown(context.tenant_id, str(message["id"]), str(exc))
            self.db.commit()
            raise RetryableJobError(str(exc)) from exc

        if result is not None:
            self._mark_attempt_sent(
                attempt_id=str(attempt["id"]),
                provider_external_id=result.external_id,
                response_payload={
                    "reconciled": True,
                    "provider_response": result.response,
                },
            )
            self._mark_message_sent(
                tenant_id=context.tenant_id,
                message_id=str(message["id"]),
                provider=result.provider,
                external_id=result.external_id,
                response={
                    "reconciled": True,
                    "provider_response": result.response,
                },
            )
            self._mark_campaign_recipient_sent(message_id=str(message["id"]))
            self.db.commit()
            return {
                "message_id": str(message["id"]),
                "provider": result.provider,
                "delivery_external_id": result.external_id,
                "reconciled": True,
            }

        if not self._reconciliation_grace_elapsed(attempt):
            raise RetryableJobError("Aguardando janela de reconciliacao antes de reenviar")

        return None

    def _create_or_load_attempt(self, *, tenant_id: str, message: dict[str, Any]):
        return (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_message_dispatch_attempts (
                        tenant_id, message_id, channel_id, provider,
                        idempotency_key, status, started_at
                    )
                    VALUES (
                        :tenant_id, :message_id, :channel_id, 'evolution',
                        :idempotency_key, 'sending', NOW()
                    )
                    ON CONFLICT (tenant_id, provider, idempotency_key)
                    DO UPDATE SET idempotency_key =
                        sales_message_dispatch_attempts.idempotency_key
                    RETURNING *
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "message_id": str(message["id"]),
                    "channel_id": str(message["channel_id"]) if message["channel_id"] else None,
                    "idempotency_key": f"sales.message:{message['id']}:evolution:v1",
                },
            )
            .mappings()
            .one()
        )

    def _mark_attempt_request(self, *, attempt_id: str, request_payload: dict[str, Any]) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_message_dispatch_attempts
                SET request_payload = CAST(:request_payload AS jsonb),
                    started_at = COALESCE(started_at, NOW())
                WHERE id = :attempt_id
                """
            ),
            {"attempt_id": attempt_id, "request_payload": _json(request_payload)},
        )

    def _mark_attempt_sent(
        self,
        *,
        attempt_id: str,
        provider_external_id: str,
        response_payload: dict[str, Any],
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_message_dispatch_attempts
                SET status = 'sent',
                    provider_external_id = :provider_external_id,
                    response_payload = CAST(:response_payload AS jsonb),
                    finished_at = NOW()
                WHERE id = :attempt_id
                """
            ),
            {
                "attempt_id": attempt_id,
                "provider_external_id": provider_external_id,
                "response_payload": _json(response_payload),
            },
        )

    def _mark_attempt_failed(self, attempt_id: str, error_code: str, error_message: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_message_dispatch_attempts
                SET status = 'failed',
                    error_code = :error_code,
                    error_message = :error_message,
                    finished_at = NOW()
                WHERE id = :attempt_id
                """
            ),
            {
                "attempt_id": attempt_id,
                "error_code": error_code[:120],
                "error_message": error_message[:2000],
            },
        )

    def _mark_attempt_unknown(self, attempt_id: str, error_code: str, error_message: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_message_dispatch_attempts
                SET error_code = :error_code,
                    error_message = :error_message
                WHERE id = :attempt_id
                """
            ),
            {
                "attempt_id": attempt_id,
                "error_code": error_code[:120],
                "error_message": error_message[:2000],
            },
        )

    def _mark_message_sending(self, tenant_id: str, message_id: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_messages
                SET status = 'sending',
                    error = NULL
                WHERE tenant_id = :tenant_id
                  AND id = :message_id
                  AND status = 'pending'
                """
            ),
            {"tenant_id": tenant_id, "message_id": message_id},
        )

    def _mark_message_sent(
        self,
        *,
        tenant_id: str,
        message_id: str,
        provider: str,
        external_id: str,
        response: dict[str, Any],
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_messages
                SET status = 'sent',
                    delivery_provider = :provider,
                    delivery_external_id = :external_id,
                    dispatched_at = COALESCE(dispatched_at, NOW()),
                    error = NULL,
                    metadata = metadata || CAST(:metadata AS jsonb)
                WHERE tenant_id = :tenant_id
                  AND id = :message_id
                  AND (
                        delivery_external_id IS NULL
                        OR delivery_external_id = :external_id
                      )
                """
            ),
            {
                "tenant_id": tenant_id,
                "message_id": message_id,
                "provider": provider,
                "external_id": external_id,
                "metadata": _json({"delivery_response": response}),
            },
        )

    def _mark_message_failed(self, tenant_id: str, message_id: str, error: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_messages
                SET status = 'failed',
                    error = :error
                WHERE tenant_id = :tenant_id
                  AND id = :message_id
                """
            ),
            {"tenant_id": tenant_id, "message_id": message_id, "error": error[:2000]},
        )

    def _mark_message_unknown(self, tenant_id: str, message_id: str, error: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_messages
                SET status = 'sending',
                    error = :error
                WHERE tenant_id = :tenant_id
                  AND id = :message_id
                """
            ),
            {"tenant_id": tenant_id, "message_id": message_id, "error": error[:2000]},
        )

    def _mark_campaign_recipient_sent(self, *, message_id: str) -> None:
        self.db.execute(
            text(
                """
                WITH updated AS (
                    UPDATE sales_campaign_recipients
                    SET status = 'sent',
                        sent_at = COALESCE(sent_at, NOW()),
                        error = NULL,
                        updated_at = NOW()
                    WHERE message_id = :message_id
                      AND status IN ('queued', 'pending', 'failed')
                    RETURNING tenant_id, campaign_id
                )
                UPDATE sales_campaigns c
                SET queued_count = counts.queued_count,
                    sent_count = counts.sent_count,
                    failed_count = counts.failed_count,
                    skipped_count = counts.skipped_count,
                    status = CASE
                        WHEN counts.queued_count > 0 THEN 'queued'
                        WHEN counts.sent_count > 0 THEN 'sent'
                        WHEN counts.failed_count > 0 THEN 'failed'
                        WHEN counts.skipped_count > 0 THEN 'failed'
                        ELSE c.status
                    END,
                    finished_at = CASE
                        WHEN counts.queued_count = 0 THEN COALESCE(c.finished_at, NOW())
                        ELSE c.finished_at
                    END,
                    updated_at = NOW()
                FROM (
                    SELECT
                        r.tenant_id,
                        r.campaign_id,
                        COUNT(*) FILTER (WHERE r.status = 'queued') AS queued_count,
                        COUNT(*) FILTER (WHERE r.status = 'sent') AS sent_count,
                        COUNT(*) FILTER (WHERE r.status = 'failed') AS failed_count,
                        COUNT(*) FILTER (WHERE r.status = 'skipped') AS skipped_count
                    FROM sales_campaign_recipients r
                    JOIN updated u
                      ON u.tenant_id = r.tenant_id
                     AND u.campaign_id = r.campaign_id
                    GROUP BY r.tenant_id, r.campaign_id
                ) counts
                WHERE c.tenant_id = counts.tenant_id
                  AND c.id = counts.campaign_id
                """
            ),
            {"message_id": message_id},
        )

    def _mark_campaign_recipient_failed(self, *, message_id: str, error: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_campaign_recipients
                SET status = 'failed',
                    error = :error,
                    updated_at = NOW()
                WHERE message_id = :message_id
                  AND status IN ('queued', 'pending')
                """
            ),
            {"message_id": message_id, "error": error[:2000]},
        )

    def _reconciliation_grace_elapsed(self, attempt) -> bool:
        if self.reconciliation_grace_seconds <= 0:
            return True
        started_at = attempt["started_at"] or attempt["created_at"]
        row = self.db.execute(
            text(
                """
                SELECT COALESCE(
                    :started_at <= NOW() - (:grace_seconds * INTERVAL '1 second'),
                    false
                )
                """
            ),
            {
                "started_at": started_at,
                "grace_seconds": self.reconciliation_grace_seconds,
            },
        ).scalar_one()
        return bool(row)


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
