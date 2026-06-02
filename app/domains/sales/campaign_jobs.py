import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.domains.jobs.registry import JobExecutionContext, PermanentJobError, job_handlers
from app.domains.sales.campaign_service import SALES_CAMPAIGN_DISPATCH_JOB


@job_handlers.register(SALES_CAMPAIGN_DISPATCH_JOB)
def dispatch_sales_campaign(context: JobExecutionContext) -> dict[str, Any]:
    with SessionLocal() as db:
        return SalesCampaignJobProcessor(db).dispatch(context)


class SalesCampaignJobProcessor:
    def __init__(self, db: Session) -> None:
        self.db = db

    def dispatch(self, context: JobExecutionContext) -> dict[str, Any]:
        campaign_id = str(context.payload.get("campaign_id") or "")
        if not campaign_id:
            raise PermanentJobError("Payload sem campaign_id")

        campaign = self._load_campaign(context.tenant_id, campaign_id)
        if campaign["status"] == "cancelled":
            raise PermanentJobError("Campanha cancelada")

        recipients = self._list_pending_recipients(context.tenant_id, campaign_id)
        if not recipients:
            counts = self._finish_campaign(context.tenant_id, campaign_id)
            self.db.commit()
            return {
                "campaign_id": campaign_id,
                "queued": 0,
                "failed": 0,
                "skipped": True,
                **counts,
            }

        queued = 0
        failed = 0
        for recipient in recipients:
            try:
                with self.db.begin_nested():
                    inserted = self._queue_recipient_message(
                        tenant_id=context.tenant_id,
                        campaign=campaign,
                        recipient=recipient,
                    )
                queued += 1 if inserted else 0
            except Exception as exc:
                failed += 1
                self._mark_recipient_failed(str(recipient["id"]), str(exc))

        counts = self._finish_campaign(context.tenant_id, campaign_id)
        self.db.commit()
        return {
            "campaign_id": campaign_id,
            "queued": queued,
            "failed": failed,
            **counts,
        }

    def _load_campaign(self, tenant_id: str, campaign_id: str):
        row = (
            self.db.execute(
                text(
                    """
                    SELECT *
                    FROM sales_campaigns
                    WHERE tenant_id = :tenant_id
                      AND id = :campaign_id
                    FOR UPDATE
                    """
                ),
                {"tenant_id": tenant_id, "campaign_id": campaign_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise PermanentJobError("Campanha nao encontrada")
        self.db.execute(
            text(
                """
                UPDATE sales_campaigns
                SET status = 'sending',
                    started_at = COALESCE(started_at, NOW()),
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :campaign_id
                  AND status NOT IN ('sent', 'queued')
                """
            ),
            {"tenant_id": tenant_id, "campaign_id": campaign_id},
        )
        return dict(row)

    def _list_pending_recipients(self, tenant_id: str, campaign_id: str) -> list[dict[str, Any]]:
        rows = (
            self.db.execute(
                text(
                    """
                    SELECT
                        r.id,
                        r.contact_id,
                        r.status,
                        c.name AS contact_name,
                        c.phone_normalized,
                        c.optout,
                        c.status AS contact_status
                    FROM sales_campaign_recipients r
                    LEFT JOIN sales_contacts c
                      ON c.id = r.contact_id
                     AND c.tenant_id = r.tenant_id
                    WHERE r.tenant_id = :tenant_id
                      AND r.campaign_id = :campaign_id
                      AND r.status IN ('pending', 'failed')
                    ORDER BY r.created_at ASC, r.id ASC
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"tenant_id": tenant_id, "campaign_id": campaign_id},
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    def _queue_recipient_message(
        self,
        *,
        tenant_id: str,
        campaign: dict[str, Any],
        recipient: dict[str, Any],
    ) -> bool:
        if not recipient["contact_id"]:
            self._mark_recipient_skipped(str(recipient["id"]), "missing_contact")
            return False
        if recipient["contact_status"] != "active" or recipient["optout"]:
            self._mark_recipient_skipped(str(recipient["id"]), "contact_ineligible")
            return False

        conversation_id = self._find_or_create_conversation(
            tenant_id=tenant_id,
            contact_id=str(recipient["contact_id"]),
            channel_id=str(campaign["channel_id"]) if campaign["channel_id"] else None,
            membership_id=str(campaign["created_by_membership_id"])
            if campaign["created_by_membership_id"]
            else None,
        )
        external_id = f"campaign:{campaign['id']}:recipient:{recipient['id']}:v1"
        inserted = (
            self.db.execute(
                text(
                    """
                    INSERT INTO sales_messages (
                        tenant_id, conversation_id, contact_id, direction,
                        sender_type, sender_membership_id, message_type, content,
                        provider, external_id, status, metadata
                    )
                    VALUES (
                        :tenant_id, :conversation_id, :contact_id, 'saida',
                        'sistema', :membership_id, :message_type, :content,
                        'labby_campaign', :external_id, 'pending',
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
                    "contact_id": recipient["contact_id"],
                    "membership_id": campaign["created_by_membership_id"],
                    "message_type": campaign["message_type"],
                    "content": campaign["content"],
                    "external_id": external_id,
                    "metadata": json.dumps(
                        {
                            "campaign_id": str(campaign["id"]),
                            "campaign_recipient_id": str(recipient["id"]),
                        },
                        ensure_ascii=False,
                    ),
                },
            )
            .mappings()
            .first()
        )
        if inserted:
            self._mark_message_side_effects(
                tenant_id=tenant_id,
                recipient_id=str(recipient["id"]),
                conversation_id=conversation_id,
                contact_id=str(recipient["contact_id"]),
                message_id=str(inserted["id"]),
                created_at=inserted["created_at"],
                membership_id=str(campaign["created_by_membership_id"])
                if campaign["created_by_membership_id"]
                else None,
            )
            return True

        existing_message = (
            self.db.execute(
                text(
                    """
                    SELECT id
                    FROM sales_messages
                    WHERE tenant_id = :tenant_id
                      AND provider = 'labby_campaign'
                      AND external_id = :external_id
                    """
                ),
                {"tenant_id": tenant_id, "external_id": external_id},
            )
            .mappings()
            .first()
        )
        self._mark_recipient_queued(
            recipient_id=str(recipient["id"]),
            conversation_id=conversation_id,
            message_id=str(existing_message["id"]) if existing_message else None,
        )
        return False

    def _find_or_create_conversation(
        self,
        *,
        tenant_id: str,
        contact_id: str,
        channel_id: str | None,
        membership_id: str | None,
    ) -> str:
        row = (
            self.db.execute(
                text(
                    """
                    SELECT id
                    FROM sales_conversations
                    WHERE tenant_id = :tenant_id
                      AND contact_id = :contact_id
                      AND (
                            (:channel_id IS NULL AND channel_id IS NULL)
                            OR channel_id = :channel_id
                      )
                      AND status != 'fechada'
                    ORDER BY last_message_at DESC NULLS LAST, created_at DESC, id DESC
                    FOR UPDATE
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id, "contact_id": contact_id, "channel_id": channel_id},
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
                        waiting_for_human, created_by_membership_id,
                        updated_by_membership_id, last_message_at
                    )
                    VALUES (
                        :tenant_id, :contact_id, :channel_id, 'aberta',
                        '[]'::jsonb, false, :membership_id, :membership_id, NOW()
                    )
                    RETURNING id
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "contact_id": contact_id,
                    "channel_id": channel_id,
                    "membership_id": membership_id,
                },
            )
            .mappings()
            .one()
        )
        return str(row["id"])

    def _mark_message_side_effects(
        self,
        *,
        tenant_id: str,
        recipient_id: str,
        conversation_id: str,
        contact_id: str,
        message_id: str,
        created_at,
        membership_id: str | None,
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_conversations
                SET last_message_at = :created_at,
                    waiting_for_human = false,
                    status = CASE WHEN status = 'fechada' THEN 'aberta' ELSE status END,
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :conversation_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "membership_id": membership_id,
                "created_at": created_at,
            },
        )
        self.db.execute(
            text(
                """
                UPDATE sales_contacts
                SET total_messages_sent = total_messages_sent + 1,
                    last_interaction_at = :created_at,
                    updated_by_membership_id = :membership_id,
                    updated_at = NOW()
                WHERE tenant_id = :tenant_id
                  AND id = :contact_id
                """
            ),
            {
                "tenant_id": tenant_id,
                "contact_id": contact_id,
                "membership_id": membership_id,
                "created_at": created_at,
            },
        )
        self._mark_recipient_queued(
            recipient_id=recipient_id,
            conversation_id=conversation_id,
            message_id=message_id,
        )

    def _mark_recipient_queued(
        self,
        *,
        recipient_id: str,
        conversation_id: str,
        message_id: str | None,
    ) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_campaign_recipients
                SET status = 'queued',
                    conversation_id = :conversation_id,
                    message_id = COALESCE(:message_id, message_id),
                    error = NULL,
                    queued_at = COALESCE(queued_at, NOW()),
                    updated_at = NOW()
                WHERE id = :recipient_id
                """
            ),
            {
                "recipient_id": recipient_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
            },
        )

    def _mark_recipient_failed(self, recipient_id: str, error: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_campaign_recipients
                SET status = 'failed',
                    error = :error,
                    updated_at = NOW()
                WHERE id = :recipient_id
                """
            ),
            {"recipient_id": recipient_id, "error": error[:2000]},
        )

    def _mark_recipient_skipped(self, recipient_id: str, error: str) -> None:
        self.db.execute(
            text(
                """
                UPDATE sales_campaign_recipients
                SET status = 'skipped',
                    error = :error,
                    updated_at = NOW()
                WHERE id = :recipient_id
                """
            ),
            {"recipient_id": recipient_id, "error": error[:2000]},
        )

    def _finish_campaign(self, tenant_id: str, campaign_id: str) -> dict[str, int]:
        row = (
            self.db.execute(
                text(
                    """
                    WITH counts AS (
                        SELECT
                            COUNT(*) AS total_recipients,
                            COUNT(*) FILTER (WHERE status = 'queued') AS queued_count,
                            COUNT(*) FILTER (WHERE status = 'sent') AS sent_count,
                            COUNT(*) FILTER (WHERE status = 'failed') AS failed_count,
                            COUNT(*) FILTER (WHERE status = 'skipped') AS skipped_count,
                            COUNT(*) FILTER (WHERE status = 'pending') AS pending_count
                        FROM sales_campaign_recipients
                        WHERE tenant_id = :tenant_id
                          AND campaign_id = :campaign_id
                    )
                    UPDATE sales_campaigns c
                    SET total_recipients = counts.total_recipients,
                        queued_count = counts.queued_count,
                        sent_count = counts.sent_count,
                        failed_count = counts.failed_count,
                        skipped_count = counts.skipped_count,
                        status = CASE
                            WHEN counts.pending_count > 0 THEN 'failed'
                            WHEN counts.queued_count > 0 THEN 'queued'
                            WHEN counts.sent_count > 0 THEN 'sent'
                            WHEN counts.skipped_count > 0 THEN 'failed'
                            ELSE 'failed'
                        END,
                        finished_at = NOW(),
                        updated_at = NOW()
                    FROM counts
                    WHERE c.tenant_id = :tenant_id
                      AND c.id = :campaign_id
                    RETURNING
                        c.total_recipients,
                        c.queued_count,
                        c.sent_count,
                        c.failed_count,
                        c.skipped_count
                    """
                ),
                {"tenant_id": tenant_id, "campaign_id": campaign_id},
            )
            .mappings()
            .one()
        )
        return {
            "total_recipients": int(row["total_recipients"] or 0),
            "queued_count": int(row["queued_count"] or 0),
            "sent_count": int(row["sent_count"] or 0),
            "failed_count": int(row["failed_count"] or 0),
            "skipped_count": int(row["skipped_count"] or 0),
        }
