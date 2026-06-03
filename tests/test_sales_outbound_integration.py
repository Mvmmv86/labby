from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domains.jobs.registry import JobExecutionContext, job_handlers
from app.domains.sales.conversation_service import SalesConversationService
from app.domains.sales.outbound_jobs import SalesOutboundJobProcessor
from app.domains.sales.outbound_service import SALES_MESSAGE_DISPATCH_JOB
from app.domains.sales.webhook_jobs import SalesWebhookJobProcessor
from app.integrations.sales_channels import OutboundSendResult
from tests.test_sales_contacts_integration import TENANT_1, current_one
from tests.test_sales_contacts_integration import (
    db_session as _db_session_fixture,  # noqa: F401
)
from tests.test_sales_contacts_integration import (
    migrated_engine as _migrated_engine_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


class FakeEvolutionOutboundAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send_message(self, **kwargs) -> OutboundSendResult:
        self.calls.append(kwargs)
        return OutboundSendResult(
            provider="evolution",
            external_id="evo-out-1",
            response={"key": {"id": "evo-out-1"}},
        )


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

    status_context = JobExecutionContext(
        job_id="status-job",
        tenant_id=str(TENANT_1),
        membership_id=None,
        job_type="sales.webhook.evolution",
        queue_name="worker-sales-webhooks",
        payload={},
        attempts=1,
    )
    SalesWebhookJobProcessor(db_session)._process_message_status_update(
        tenant_id=str(TENANT_1),
        payload={
            "data": {
                "key": {"id": "evo-out-1"},
                "status": "delivery_ack",
            }
        },
    )
    assert status_context.tenant_id == str(TENANT_1)
    db_session.commit()

    assert db_session.execute(
        text("SELECT status FROM sales_messages WHERE id = :message_id"),
        {"message_id": sent["id"]},
    ).scalar_one() == "delivered"


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


def count_rows(session: Session, table_name: str) -> int:
    return session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
