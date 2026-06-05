
import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

import app.domains.sales.webhook_service as webhook_service_module
from app.core.rate_limit import RateLimitDecision, RateLimitUnavailable
from app.domains.jobs.registry import JobExecutionContext, job_handlers
from app.domains.sales.channel_service import SalesChannelService
from app.domains.sales.webhook_jobs import SalesWebhookJobProcessor
from app.domains.sales.webhook_service import (
    SALES_EVOLUTION_WEBHOOK_JOB,
    SalesWebhookReceiver,
)
from tests.test_sales_contacts_integration import TENANT_1, current_one
from tests.test_sales_contacts_integration import (
    db_session as _db_session_fixture,  # noqa: F401
)
from tests.test_sales_contacts_integration import (
    migrated_engine as _migrated_engine_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


class FakeRateLimiter:
    def __init__(self, *, allowed: bool = True, unavailable: bool = False) -> None:
        self.allowed = allowed
        self.unavailable = unavailable
        self.calls: list[dict] = []

    def check(self, **kwargs) -> RateLimitDecision:
        self.calls.append(kwargs)
        if self.unavailable:
            raise RateLimitUnavailable("down")
        return RateLimitDecision(
            allowed=self.allowed,
            current=1 if self.allowed else kwargs["limit"] + 1,
            retry_after_seconds=60,
        )


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
    db_session.execute(
        text("UPDATE sales_channels SET status = 'conectado' WHERE id = :channel_id"),
        {"channel_id": channel["id"]},
    )
    db_session.commit()
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


def test_evolution_webhook_ignores_message_when_channel_disconnected(
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
                "id": "wa-message-disconnected",
                "remoteJid": "5511999990001@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "Lead Sem Canal",
            "message": {"conversation": "Ainda quero falar"},
        },
    }
    receiver = SalesWebhookReceiver(db_session)

    ignored = receiver.receive_evolution(
        channel_id=str(channel["id"]),
        payload=payload,
        headers={"x-labby-webhook-secret": secret},
    )
    duplicate = receiver.receive_evolution(
        channel_id=str(channel["id"]),
        payload=payload,
        headers={"x-labby-webhook-secret": secret},
    )

    assert ignored["status"] == "ignored"
    assert ignored["job_id"] is None
    assert ignored["duplicate"] is False
    assert duplicate["status"] == "ignored"
    assert duplicate["duplicate"] is True
    assert count_rows(db_session, "webhook_events") == 1
    assert count_rows(db_session, "jobs") == 0
    assert count_rows(db_session, "sales_messages") == 0

    event = db_session.execute(
        text(
            """
            SELECT status, error_code, job_id
            FROM webhook_events
            WHERE id = :event_id
            """
        ),
        {"event_id": ignored["webhook_event_id"]},
    ).mappings().one()
    assert event["status"] == "ignored"
    assert event["error_code"] == "channel_not_connected"
    assert event["job_id"] is None


def test_evolution_lifecycle_event_queues_even_when_channel_is_not_connected(
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

    queued = SalesWebhookReceiver(db_session).receive_evolution(
        channel_id=str(channel["id"]),
        payload={"event": "connection.update", "data": {"state": "open"}},
        headers={"x-labby-webhook-secret": secret},
    )

    assert queued["status"] == "queued"
    assert queued["job_id"] is not None
    assert count_rows(db_session, "webhook_events") == 1
    assert count_rows(db_session, "jobs") == 1


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


def test_evolution_webhook_rate_limit_uses_channel_backstop(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        webhook_service_module,
        "EVOLUTION_WEBHOOK_LIMIT_PER_CHANNEL_PER_MINUTE",
        3,
    )
    channel = SalesChannelService(db_session).create_channel(
        current=current_one(),
        tipo="whatsapp_evolution",
        nome="WhatsApp",
    )
    secret = db_session.execute(
        text("SELECT webhook_secret FROM sales_channels WHERE id = :channel_id"),
        {"channel_id": channel["id"]},
    ).scalar_one()
    db_session.execute(
        text("UPDATE sales_channels SET status = 'conectado' WHERE id = :channel_id"),
        {"channel_id": channel["id"]},
    )
    db_session.commit()
    receiver = SalesWebhookReceiver(db_session)
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {
                "id": "wa-rate-limit",
                "remoteJid": "5511999990000@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {"conversation": "Oi"},
        },
    }

    for _ in range(3):
        response = receiver.receive_evolution(
            channel_id=str(channel["id"]),
            payload=payload,
            headers={"x-labby-webhook-secret": secret},
            client_ip="203.0.113.10",
        )
        assert response["status"] == "queued"

    with pytest.raises(HTTPException) as exc:
        receiver.receive_evolution(
            channel_id=str(channel["id"]),
            payload=payload,
            headers={"x-labby-webhook-secret": secret},
            client_ip="203.0.113.10",
        )
    assert exc.value.status_code == 429


def test_evolution_webhook_wrong_secret_does_not_consume_channel_rate_limit(
    db_session: Session,
) -> None:
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
            client_ip="203.0.113.10",
        )

    assert exc.value.status_code == 401
    assert db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM rate_limit_events
            WHERE tenant_id = :tenant_id
              AND provider = 'evolution'
              AND action = 'webhook.evolution.channel'
            """
        ),
        {"tenant_id": TENANT_1},
    ).scalar_one() == 0


def test_evolution_webhook_redis_rate_limit_does_not_write_allowed_events(
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
    db_session.execute(
        text("UPDATE sales_channels SET status = 'conectado' WHERE id = :channel_id"),
        {"channel_id": channel["id"]},
    )
    db_session.commit()
    limiter = FakeRateLimiter(allowed=True)

    response = SalesWebhookReceiver(db_session, rate_limiter=limiter).receive_evolution(
        channel_id=str(channel["id"]),
        payload={
            "event": "messages.upsert",
            "data": {
                "key": {
                    "id": "wa-redis-allowed",
                    "remoteJid": "5511999990000@s.whatsapp.net",
                    "fromMe": False,
                },
                "message": {"conversation": "Oi"},
            },
        },
        headers={"x-labby-webhook-secret": secret},
        client_ip="203.0.113.10",
    )

    assert response["status"] == "queued"
    assert len(limiter.calls) == 1
    assert db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM rate_limit_events
            WHERE tenant_id = :tenant_id
              AND provider = 'evolution'
            """
        ),
        {"tenant_id": TENANT_1},
    ).scalar_one() == 0


def test_evolution_webhook_redis_rate_limit_records_blocked_event(
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
    db_session.execute(
        text("UPDATE sales_channels SET status = 'conectado' WHERE id = :channel_id"),
        {"channel_id": channel["id"]},
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        SalesWebhookReceiver(
            db_session,
            rate_limiter=FakeRateLimiter(allowed=False),
        ).receive_evolution(
            channel_id=str(channel["id"]),
            payload={
                "event": "messages.upsert",
                "data": {
                    "key": {
                        "id": "wa-redis-blocked",
                        "remoteJid": "5511999990000@s.whatsapp.net",
                        "fromMe": False,
                    },
                    "message": {"conversation": "Oi"},
                },
            },
            headers={"x-labby-webhook-secret": secret},
            client_ip="203.0.113.10",
        )

    assert exc.value.status_code == 429
    blocked = db_session.execute(
        text(
            """
            SELECT outcome, metadata_json
            FROM rate_limit_events
            WHERE tenant_id = :tenant_id
              AND provider = 'evolution'
            """
        ),
        {"tenant_id": TENANT_1},
    ).mappings().one()
    assert blocked["outcome"] == "blocked"
    assert blocked["metadata_json"]["backend"] == "redis"


def test_evolution_webhook_redis_outage_falls_back_to_database_rate_limit(
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
    db_session.execute(
        text("UPDATE sales_channels SET status = 'conectado' WHERE id = :channel_id"),
        {"channel_id": channel["id"]},
    )
    db_session.commit()
    limiter = FakeRateLimiter(unavailable=True)

    response = SalesWebhookReceiver(db_session, rate_limiter=limiter).receive_evolution(
        channel_id=str(channel["id"]),
        payload={
            "event": "messages.upsert",
            "data": {
                "key": {
                    "id": "wa-redis-outage",
                    "remoteJid": "5511999990000@s.whatsapp.net",
                    "fromMe": False,
                },
                "message": {"conversation": "Oi"},
            },
        },
        headers={"x-labby-webhook-secret": secret},
        client_ip="203.0.113.10",
    )

    assert response["status"] == "queued"
    assert len(limiter.calls) == 1
    event = db_session.execute(
        text(
            """
            SELECT outcome, metadata_json
            FROM rate_limit_events
            WHERE tenant_id = :tenant_id
              AND provider = 'evolution'
              AND action = 'webhook.evolution.channel'
            """
        ),
        {"tenant_id": TENANT_1},
    ).mappings().one()
    assert event["outcome"] == "allowed"
    assert event["metadata_json"]["backend"] == "database_fallback"


def test_non_evolution_external_connect_is_gated_until_inbound_exists(
    db_session: Session,
) -> None:
    service = SalesChannelService(db_session)
    channel = service.create_channel(
        current=current_one(),
        tipo="telegram",
        nome="Telegram",
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.connect_channel(
                current=current_one(),
                channel_id=str(channel["id"]),
                data={"bot_token": "token"},
            )
        )

    assert exc.value.status_code == 501
    status = db_session.execute(
        text("SELECT status FROM sales_channels WHERE id = :channel_id"),
        {"channel_id": channel["id"]},
    ).scalar_one()
    assert status == "desconectado"


def count_rows(session: Session, table_name: str) -> int:
    return session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
