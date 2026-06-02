
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domains.jobs.registry import JobExecutionContext, job_handlers
from app.domains.sales.channel_service import SalesChannelService
from app.domains.sales.webhook_jobs import SalesWebhookJobProcessor
from app.domains.sales.webhook_service import SALES_EVOLUTION_WEBHOOK_JOB, SalesWebhookReceiver
from tests.test_sales_contacts_integration import TENANT_1, current_one
from tests.test_sales_contacts_integration import (
    db_session as _db_session_fixture,  # noqa: F401
)
from tests.test_sales_contacts_integration import (
    migrated_engine as _migrated_engine_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


def test_sales_evolution_webhook_handler_is_registered() -> None:
    assert job_handlers.get(SALES_EVOLUTION_WEBHOOK_JOB) is not None


def test_sales_channel_service_redacts_secret_config(db_session: Session) -> None:
    service = SalesChannelService(db_session)

    channel = service.create_channel(
        current=current_one(),
        tipo="whatsapp_cloud",
        nome="Cloud",
        config={"access_token": "secret-token", "phone_number": "5511999990000"},
    )

    assert channel["config"]["access_token"] == "***"
    assert channel["config"]["phone_number"] == "5511999990000"


def test_evolution_webhook_records_event_job_and_ingests_message_once(
    db_session: Session,
) -> None:
    channel = SalesChannelService(db_session).create_channel(
        current=current_one(),
        tipo="whatsapp_evolution",
        nome="WhatsApp",
    )
    secret = db_session.execute(
        text("SELECT webhook_secret FROM sales_channels WHERE id = :channel_id"),
        {"channel_id": channel["id"]},
    ).scalar_one()
    payload = {
        "event": "messages.upsert",
        "instance": "labby_test",
        "data": {
            "key": {
                "id": "wa-message-1",
                "remoteJid": "5511999990000@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "Paula Lead",
            "message": {"conversation": "Oi, quero comprar"},
        },
    }
    receiver = SalesWebhookReceiver(db_session)

    queued = receiver.receive_evolution(
        channel_id=str(channel["id"]),
        payload=payload,
        headers={"x-labby-webhook-secret": secret},
    )
    duplicate = receiver.receive_evolution(
        channel_id=str(channel["id"]),
        payload=payload,
        headers={"x-labby-webhook-secret": secret},
    )

    assert queued["status"] == "queued"
    assert queued["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert duplicate["job_id"] == queued["job_id"]
    assert count_rows(db_session, "webhook_events") == 1
    assert count_rows(db_session, "jobs") == 1

    job = db_session.execute(
        text("SELECT * FROM jobs WHERE id = :job_id"),
        {"job_id": queued["job_id"]},
    ).mappings().one()
    context = JobExecutionContext(
        job_id=str(job["id"]),
        tenant_id=str(job["tenant_id"]),
        membership_id=None,
        job_type=str(job["job_type"]),
        queue_name=str(job["queue_name"]),
        payload=dict(job["payload"]),
        attempts=1,
    )

    result = SalesWebhookJobProcessor(db_session).process_evolution(context)
    skipped = SalesWebhookJobProcessor(db_session).process_evolution(context)

    assert result["message_inserted"] is True
    assert skipped["skipped"] is True
    assert count_rows(db_session, "sales_contacts") == 1
    assert count_rows(db_session, "sales_conversations") == 1
    assert count_rows(db_session, "sales_messages") == 1

    row = db_session.execute(
        text(
            """
            SELECT
                c.name,
                c.phone_normalized,
                c.total_messages_received,
                conv.waiting_for_human,
                m.content,
                m.provider,
                m.external_id
            FROM sales_contacts c
            JOIN sales_conversations conv
              ON conv.contact_id = c.id
             AND conv.tenant_id = c.tenant_id
            JOIN sales_messages m
              ON m.conversation_id = conv.id
             AND m.tenant_id = conv.tenant_id
            WHERE c.tenant_id = :tenant_id
            """
        ),
        {"tenant_id": TENANT_1},
    ).mappings().one()
    assert row["name"] == "Paula Lead"
    assert row["phone_normalized"] == "5511999990000"
    assert row["total_messages_received"] == 1
    assert row["waiting_for_human"] is True
    assert row["content"] == "Oi, quero comprar"
    assert row["provider"] == "evolution"
    assert row["external_id"] == "wa-message-1"


def test_evolution_webhook_rejects_wrong_secret(db_session: Session) -> None:
    channel = SalesChannelService(db_session).create_channel(
        current=current_one(),
        tipo="whatsapp_evolution",
        nome="WhatsApp",
    )

    with pytest.raises(HTTPException) as exc:
        SalesWebhookReceiver(db_session).receive_evolution(
            channel_id=str(channel["id"]),
            payload={"event": "messages.upsert"},
            headers={"x-labby-webhook-secret": "wrong"},
        )

    assert exc.value.status_code == 401


def count_rows(session: Session, table_name: str) -> int:
    return session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
