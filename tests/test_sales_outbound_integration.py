from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domains.jobs.registry import (
    JobExecutionContext,
    PermanentJobError,
    RetryableJobError,
    job_handlers,
)
from app.domains.sales.conversation_service import SalesConversationService
from app.domains.sales.outbound_jobs import SalesOutboundJobProcessor
from app.domains.sales.outbound_service import SALES_MESSAGE_DISPATCH_JOB
from app.domains.sales.webhook_jobs import SalesWebhookJobProcessor
from app.integrations.sales_channels import (
    OutboundDeliveryUnknown,
    OutboundProviderError,
    OutboundReconcileResult,
    OutboundSendResult,
)
from tests.test_sales_contacts_integration import TENANT_1, current_one
from tests.test_sales_contacts_integration import (
    db_session as _db_session_fixture,  # noqa: F401
)
from tests.test_sales_contacts_integration import (
    migrated_engine as _migrated_engine_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


class FakeEvolutionOutboundAdapter:
    def __init__(self, *, external_id: str = "evo-out-1") -> None:
        self.calls: list[dict[str, Any]] = []
        self.external_id = external_id

    async def send_message(self, **kwargs) -> OutboundSendResult:
        self.calls.append(kwargs)
        return OutboundSendResult(
            provider="evolution",
            external_id=self.external_id,
            response={"key": {"id": self.external_id}},
        )

    async def reconcile_message(self, **kwargs) -> OutboundReconcileResult | None:
        return None


class FailingEvolutionOutboundAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_message(self, **kwargs) -> OutboundSendResult:
        self.calls.append(kwargs)
        raise OutboundProviderError("timeout")

    async def reconcile_message(self, **kwargs) -> OutboundReconcileResult | None:
        return None


class UnknownEvolutionOutboundAdapter(FakeEvolutionOutboundAdapter):
    async def send_message(self, **kwargs) -> OutboundSendResult:
        self.calls.append(kwargs)
        raise OutboundDeliveryUnknown("timeout")


class ReconcileFoundEvolutionOutboundAdapter(FakeEvolutionOutboundAdapter):
    def __init__(self, *, external_id: str = "evo-reconciled-1") -> None:
        super().__init__(external_id=external_id)
        self.reconcile_calls: list[dict[str, Any]] = []

    async def reconcile_message(self, **kwargs) -> OutboundReconcileResult | None:
        self.reconcile_calls.append(kwargs)
        return OutboundReconcileResult(
            provider="evolution",
            external_id=self.external_id,
            response={"key": {"id": self.external_id}, "metadata": kwargs["idempotency_key"]},
        )


class ReconcileMissingEvolutionOutboundAdapter(FakeEvolutionOutboundAdapter):
    def __init__(self, *, external_id: str = "evo-resend-1") -> None:
        super().__init__(external_id=external_id)
        self.reconcile_calls: list[dict[str, Any]] = []

    async def reconcile_message(self, **kwargs) -> OutboundReconcileResult | None:
        self.reconcile_calls.append(kwargs)
        return None


def test_sales_outbound_handler_is_registered() -> None:
    assert job_handlers.get(SALES_MESSAGE_DISPATCH_JOB) is not None


def test_manual_message_dispatches_once_and_reconciles_status(
    db_session: Session,
) -> None:
    conversation_id = create_evolution_conversation(db_session)
    sent = SalesConversationService(db_session).send_message(
        current=current_one(),
        conversation_id=str(conversation_id),
        conteudo="Ola, Paula",
    )
    assert sent["status"] == "pending"

    job = db_session.execute(
        text(
            """
            SELECT *
            FROM jobs
            WHERE job_type = :job_type
            """
        ),
        {"job_type": SALES_MESSAGE_DISPATCH_JOB},
    ).mappings().one()
    context = JobExecutionContext(
        job_id=str(job["id"]),
        tenant_id=str(job["tenant_id"]),
        membership_id=str(job["membership_id"]) if job["membership_id"] else None,
        job_type=str(job["job_type"]),
        queue_name=str(job["queue_name"]),
        payload=dict(job["payload"]),
        attempts=1,
    )
    assert job["max_attempts"] == 3
    adapter = FakeEvolutionOutboundAdapter()
    processor = SalesOutboundJobProcessor(db_session, evolution_adapter=adapter)

    result = processor.dispatch(context)
    skipped = processor.dispatch(context)

    assert result["delivery_external_id"] == "evo-out-1"
    assert skipped["skipped"] is True
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["recipient_identifier"] == "5511999990000@s.whatsapp.net"
    assert adapter.calls[0]["content"] == "Ola, Paula"
    assert count_rows(db_session, "sales_message_dispatch_attempts") == 1

    message = db_session.execute(
        text(
            """
            SELECT status, delivery_provider, delivery_external_id
            FROM sales_messages
            WHERE id = :message_id
            """
        ),
        {"message_id": sent["id"]},
    ).mappings().one()
    assert message["status"] == "sent"
    assert message["delivery_provider"] == "evolution"
    assert message["delivery_external_id"] == "evo-out-1"

    SalesWebhookJobProcessor(db_session)._process_message_status_update(
        tenant_id=str(TENANT_1),
        payload={
            "data": {
                "key": {"id": "evo-out-1"},
                "status": "delivery_ack",
            }
        },
    )
    db_session.commit()

    assert db_session.execute(
        text("SELECT status FROM sales_messages WHERE id = :message_id"),
        {"message_id": sent["id"]},
    ).scalar_one() == "delivered"

    SalesWebhookJobProcessor(db_session)._process_message_status_update(
        tenant_id=str(TENANT_1),
        payload={"data": {"key": {"id": "evo-out-1"}, "status": "server_ack"}},
    )
    db_session.commit()
    assert db_session.execute(
        text("SELECT status FROM sales_messages WHERE id = :message_id"),
        {"message_id": sent["id"]},
    ).scalar_one() == "delivered"

    SalesWebhookJobProcessor(db_session)._process_message_status_update(
        tenant_id=str(TENANT_1),
        payload={"data": {"key": {"id": "evo-out-1"}, "status": "read"}},
    )
    db_session.commit()
    assert db_session.execute(
        text("SELECT status FROM sales_messages WHERE id = :message_id"),
        {"message_id": sent["id"]},
    ).scalar_one() == "read"


def test_outbound_fail_closed_when_message_is_already_sending(db_session: Session) -> None:
    conversation_id = create_evolution_conversation(db_session)
    sent = SalesConversationService(db_session).send_message(
        current=current_one(),
        conversation_id=str(conversation_id),
        conteudo="Ola, Paula",
    )
    db_session.execute(
        text("UPDATE sales_messages SET status = 'sending' WHERE id = :message_id"),
        {"message_id": sent["id"]},
    )
    db_session.commit()
    adapter = FakeEvolutionOutboundAdapter()

    with pytest.raises(PermanentJobError):
        SalesOutboundJobProcessor(db_session, evolution_adapter=adapter).dispatch(
            context_for_message(str(sent["id"]))
        )

    assert adapter.calls == []
    row = db_session.execute(
        text("SELECT status, error FROM sales_messages WHERE id = :message_id"),
        {"message_id": sent["id"]},
    ).mappings().one()
    assert row["status"] == "failed"
    assert "Reconciliacao manual" in row["error"]


def test_outbound_provider_error_marks_message_and_attempt_failed(
    db_session: Session,
) -> None:
    conversation_id = create_evolution_conversation(db_session)
    sent = SalesConversationService(db_session).send_message(
        current=current_one(),
        conversation_id=str(conversation_id),
        conteudo="Ola, Paula",
    )
    adapter = FailingEvolutionOutboundAdapter()

    with pytest.raises(PermanentJobError):
        SalesOutboundJobProcessor(db_session, evolution_adapter=adapter).dispatch(
            context_for_message(str(sent["id"]))
        )

    assert len(adapter.calls) == 1
    message = db_session.execute(
        text("SELECT status, error FROM sales_messages WHERE id = :message_id"),
        {"message_id": sent["id"]},
    ).mappings().one()
    assert message["status"] == "failed"
    assert message["error"] == "timeout"
    attempt = db_session.execute(
        text(
            """
            SELECT status, error_code, error_message
            FROM sales_message_dispatch_attempts
            WHERE message_id = :message_id
            """
        ),
        {"message_id": sent["id"]},
    ).mappings().one()
    assert attempt["status"] == "failed"
    assert attempt["error_code"] == "OutboundProviderError"
    assert attempt["error_message"] == "timeout"


def test_outbound_delivery_unknown_stays_sending_for_reconciliation(
    db_session: Session,
) -> None:
    conversation_id = create_evolution_conversation(db_session)
    sent = SalesConversationService(db_session).send_message(
        current=current_one(),
        conversation_id=str(conversation_id),
        conteudo="Ola, Paula",
    )
    adapter = UnknownEvolutionOutboundAdapter()

    with pytest.raises(RetryableJobError):
        SalesOutboundJobProcessor(db_session, evolution_adapter=adapter).dispatch(
            context_for_message(str(sent["id"]))
        )

    assert len(adapter.calls) == 1
    message = db_session.execute(
        text("SELECT status, error FROM sales_messages WHERE id = :message_id"),
        {"message_id": sent["id"]},
    ).mappings().one()
    assert message["status"] == "sending"
    assert message["error"] == "timeout"
    attempt = db_session.execute(
        text(
            """
            SELECT status, error_code, error_message
            FROM sales_message_dispatch_attempts
            WHERE message_id = :message_id
            """
        ),
        {"message_id": sent["id"]},
    ).mappings().one()
    assert attempt["status"] == "sending"
    assert attempt["error_code"] == "OutboundDeliveryUnknown"
    assert attempt["error_message"] == "timeout"


def test_outbound_retry_reconciles_found_message_without_resending(
    db_session: Session,
) -> None:
    conversation_id = create_evolution_conversation(db_session)
    sent = SalesConversationService(db_session).send_message(
        current=current_one(),
        conversation_id=str(conversation_id),
        conteudo="Ola, Paula",
    )
    with pytest.raises(RetryableJobError):
        SalesOutboundJobProcessor(
            db_session,
            evolution_adapter=UnknownEvolutionOutboundAdapter(),
        ).dispatch(context_for_message(str(sent["id"])))

    adapter = ReconcileFoundEvolutionOutboundAdapter()
    result = SalesOutboundJobProcessor(
        db_session,
        evolution_adapter=adapter,
        reconciliation_grace_seconds=0,
    ).dispatch(context_for_message(str(sent["id"]), attempts=2))

    assert result["reconciled"] is True
    assert result["delivery_external_id"] == "evo-reconciled-1"
    assert adapter.calls == []
    assert len(adapter.reconcile_calls) == 1
    message = db_session.execute(
        text(
            """
            SELECT status, delivery_external_id
            FROM sales_messages
            WHERE id = :message_id
            """
        ),
        {"message_id": sent["id"]},
    ).mappings().one()
    assert message["status"] == "sent"
    assert message["delivery_external_id"] == "evo-reconciled-1"


def test_outbound_retry_waits_grace_before_resend_when_reconciliation_missing(
    db_session: Session,
) -> None:
    conversation_id = create_evolution_conversation(db_session)
    sent = SalesConversationService(db_session).send_message(
        current=current_one(),
        conversation_id=str(conversation_id),
        conteudo="Ola, Paula",
    )
    with pytest.raises(RetryableJobError):
        SalesOutboundJobProcessor(
            db_session,
            evolution_adapter=UnknownEvolutionOutboundAdapter(),
        ).dispatch(context_for_message(str(sent["id"])))

    adapter = ReconcileMissingEvolutionOutboundAdapter()
    with pytest.raises(RetryableJobError):
        SalesOutboundJobProcessor(
            db_session,
            evolution_adapter=adapter,
            reconciliation_grace_seconds=60,
        ).dispatch(context_for_message(str(sent["id"]), attempts=2))

    assert len(adapter.reconcile_calls) == 1
    assert adapter.calls == []


def test_outbound_retry_resends_only_after_reconciliation_query(
    db_session: Session,
) -> None:
    conversation_id = create_evolution_conversation(db_session)
    sent = SalesConversationService(db_session).send_message(
        current=current_one(),
        conversation_id=str(conversation_id),
        conteudo="Ola, Paula",
    )
    with pytest.raises(RetryableJobError):
        SalesOutboundJobProcessor(
            db_session,
            evolution_adapter=UnknownEvolutionOutboundAdapter(),
        ).dispatch(context_for_message(str(sent["id"])))

    adapter = ReconcileMissingEvolutionOutboundAdapter()
    result = SalesOutboundJobProcessor(
        db_session,
        evolution_adapter=adapter,
        reconciliation_grace_seconds=0,
    ).dispatch(context_for_message(str(sent["id"]), attempts=2))

    assert len(adapter.reconcile_calls) == 1
    assert len(adapter.calls) == 1
    assert result["delivery_external_id"] == "evo-resend-1"


def test_outbound_dispatch_marks_campaign_recipient_sent(db_session: Session) -> None:
    message_id = create_campaign_message(db_session)
    adapter = FakeEvolutionOutboundAdapter(external_id="evo-campaign-1")

    SalesOutboundJobProcessor(db_session, evolution_adapter=adapter).dispatch(
        context_for_message(str(message_id))
    )

    recipient = db_session.execute(
        text(
            """
            SELECT r.status, c.status AS campaign_status, c.queued_count, c.sent_count
            FROM sales_campaign_recipients r
            JOIN sales_campaigns c ON c.id = r.campaign_id
            WHERE r.message_id = :message_id
            """
        ),
        {"message_id": message_id},
    ).mappings().one()
    assert recipient["status"] == "sent"
    assert recipient["campaign_status"] == "sent"
    assert recipient["queued_count"] == 0
    assert recipient["sent_count"] == 1


def create_evolution_conversation(session: Session) -> UUID:
    channel_id = session.execute(
        text(
            """
            INSERT INTO sales_channels (
                tenant_id, channel_type, name, status, config, webhook_secret
            )
            VALUES (
                :tenant_id, 'whatsapp_evolution', 'WhatsApp', 'conectado',
                '{"instance_name": "labby_test"}'::jsonb, 'secret'
            )
            RETURNING id
            """
        ),
        {"tenant_id": TENANT_1},
    ).scalar_one()
    contact_id = session.execute(
        text(
            """
            INSERT INTO sales_contacts (
                tenant_id, name, phone, phone_normalized, tags, custom_fields
            )
            VALUES (
                :tenant_id, 'Paula', '5511999990000', '5511999990000',
                '[]'::jsonb, '{}'::jsonb
            )
            RETURNING id
            """
        ),
        {"tenant_id": TENANT_1},
    ).scalar_one()
    session.execute(
        text(
            """
            INSERT INTO sales_contact_channels (
                tenant_id, contact_id, channel_id, channel_type, identifier, metadata
            )
            VALUES (
                :tenant_id, :contact_id, :channel_id, 'whatsapp_evolution',
                '5511999990000@s.whatsapp.net', '{}'::jsonb
            )
            """
        ),
        {
            "tenant_id": TENANT_1,
            "contact_id": contact_id,
            "channel_id": channel_id,
        },
    )
    conversation_id = session.execute(
        text(
            """
            INSERT INTO sales_conversations (
                tenant_id, contact_id, channel_id, status, tags
            )
            VALUES (
                :tenant_id, :contact_id, :channel_id, 'aberta', '[]'::jsonb
            )
            RETURNING id
            """
        ),
        {
            "tenant_id": TENANT_1,
            "contact_id": contact_id,
            "channel_id": channel_id,
        },
    ).scalar_one()
    session.commit()
    return UUID(str(conversation_id))


def create_campaign_message(session: Session) -> UUID:
    conversation_id = create_evolution_conversation(session)
    conversation = session.execute(
        text(
            """
            SELECT contact_id, channel_id
            FROM sales_conversations
            WHERE id = :conversation_id
            """
        ),
        {"conversation_id": conversation_id},
    ).mappings().one()
    campaign_id = session.execute(
        text(
            """
            INSERT INTO sales_campaigns (
                tenant_id, channel_id, name, content, status, idempotency_key,
                total_recipients, queued_count, created_by_membership_id
            )
            VALUES (
                :tenant_id, :channel_id, 'Campanha', 'Ola campanha', 'queued',
                'campaign:test-outbound', 1, 1, :membership_id
            )
            RETURNING id
            """
        ),
        {
            "tenant_id": TENANT_1,
            "channel_id": conversation["channel_id"],
            "membership_id": current_one().membership_id,
        },
    ).scalar_one()
    recipient_id = session.execute(
        text(
            """
            INSERT INTO sales_campaign_recipients (
                tenant_id, campaign_id, contact_id, conversation_id, status,
                recipient_name
            )
            VALUES (
                :tenant_id, :campaign_id, :contact_id, :conversation_id,
                'queued', 'Paula'
            )
            RETURNING id
            """
        ),
        {
            "tenant_id": TENANT_1,
            "campaign_id": campaign_id,
            "contact_id": conversation["contact_id"],
            "conversation_id": conversation_id,
        },
    ).scalar_one()
    message_id = session.execute(
        text(
            """
            INSERT INTO sales_messages (
                tenant_id, conversation_id, contact_id, direction, sender_type,
                sender_membership_id, message_type, content, provider, external_id, status
            )
            VALUES (
                :tenant_id, :conversation_id, :contact_id, 'saida', 'sistema',
                :membership_id, 'text', 'Ola campanha', 'labby_campaign',
                :external_id, 'pending'
            )
            RETURNING id
            """
        ),
        {
            "tenant_id": TENANT_1,
            "conversation_id": conversation_id,
            "contact_id": conversation["contact_id"],
            "membership_id": current_one().membership_id,
            "external_id": f"campaign:{campaign_id}:recipient:{recipient_id}:v1",
        },
    ).scalar_one()
    session.execute(
        text(
            """
            UPDATE sales_campaign_recipients
            SET message_id = :message_id
            WHERE id = :recipient_id
            """
        ),
        {"message_id": message_id, "recipient_id": recipient_id},
    )
    session.commit()
    return UUID(str(message_id))


def context_for_message(message_id: str, *, attempts: int = 1) -> JobExecutionContext:
    return JobExecutionContext(
        job_id="outbound-job",
        tenant_id=str(TENANT_1),
        membership_id=str(current_one().membership_id),
        job_type=SALES_MESSAGE_DISPATCH_JOB,
        queue_name="worker-sales-outbound",
        payload={"message_id": message_id},
        attempts=attempts,
    )


def count_rows(session: Session, table_name: str) -> int:
    return session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
