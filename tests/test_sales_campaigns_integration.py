from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domains.jobs.registry import JobExecutionContext, job_handlers
from app.domains.sales.campaign_jobs import SalesCampaignJobProcessor
from app.domains.sales.campaign_service import SALES_CAMPAIGN_DISPATCH_JOB, SalesCampaignService
from app.domains.sales.contact_service import SalesContactService
from tests.test_sales_contacts_integration import TENANT_1, current_one, current_two
from tests.test_sales_contacts_integration import (
    db_session as _db_session_fixture,  # noqa: F401
)
from tests.test_sales_contacts_integration import (
    migrated_engine as _migrated_engine_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


def test_sales_campaign_dispatch_handler_is_registered() -> None:
    assert job_handlers.get(SALES_CAMPAIGN_DISPATCH_JOB) is not None


def test_campaign_dispatch_is_tenant_scoped_and_idempotent(
    db_session: Session,
) -> None:
    contact_one = create_contact(
        db_session,
        nome="Paula",
        telefone="(11) 99999-0000",
    )
    contact_two = create_contact(
        db_session,
        nome="Marcos",
        telefone="(11) 99998-0000",
    )
    optout_contact = create_contact(
        db_session,
        nome="Optout",
        telefone="(11) 99997-0000",
    )
    db_session.execute(
        text("UPDATE sales_contacts SET optout = true WHERE id = :contact_id"),
        {"contact_id": optout_contact},
    )
    db_session.commit()
    channel_id = create_channel(db_session, tenant_id=TENANT_1)

    service = SalesCampaignService(db_session)
    campaign = service.create_campaign(
        current=current_one(),
        nome="Promo Junho",
        conteudo="Ola, temos uma oferta para voce",
        channel_id=str(channel_id),
        contact_ids=[str(contact_one), str(contact_two), str(optout_contact)],
        idempotency_key="campaign:promo-junho",
    )

    assert campaign["total_destinatarios"] == 2
    duplicate_add = service.add_recipients(
        current=current_one(),
        campaign_id=str(campaign["id"]),
        contact_ids=[str(contact_one), str(contact_two)],
    )
    assert duplicate_add["inserted"] == 0
    assert duplicate_add["duplicates"] == 2
    preview = service.preview_recipients(current=current_one(), campaign_id=str(campaign["id"]))
    assert preview["total"] == 2
    started = service.start_campaign(current=current_one(), campaign_id=str(campaign["id"]))
    assert started["status"] == "ativa"

    first_dispatch = service.dispatch_campaign(
        current=current_one(),
        campaign_id=str(campaign["id"]),
    )
    duplicate_dispatch = service.dispatch_campaign(
        current=current_one(),
        campaign_id=str(campaign["id"]),
    )

    assert first_dispatch["duplicate"] is False
    assert duplicate_dispatch["duplicate"] is True
    assert duplicate_dispatch["job_id"] == first_dispatch["job_id"]
    assert count_rows(db_session, "jobs") == 1

    job = db_session.execute(
        text("SELECT * FROM jobs WHERE id = :job_id"),
        {"job_id": first_dispatch["job_id"]},
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

    result = SalesCampaignJobProcessor(db_session).dispatch(context)
    skipped = SalesCampaignJobProcessor(db_session).dispatch(context)

    assert result["queued_count"] == 2
    assert skipped["skipped"] is True
    assert count_rows(db_session, "sales_messages") == 2
    assert count_rows(db_session, "sales_conversations") == 2
    assert count_rows(db_session, "sales_campaign_recipients") == 2

    recipient_statuses = db_session.execute(
        text(
            """
            SELECT status, COUNT(*) AS total
            FROM sales_campaign_recipients
            WHERE tenant_id = :tenant_id
            GROUP BY status
            """
        ),
        {"tenant_id": TENANT_1},
    ).mappings().all()
    assert {row["status"]: int(row["total"]) for row in recipient_statuses} == {"queued": 2}

    campaign_row = db_session.execute(
        text(
            """
            SELECT status, total_recipients, queued_count, failed_count
            FROM sales_campaigns
            WHERE id = :campaign_id
            """
        ),
        {"campaign_id": campaign["id"]},
    ).mappings().one()
    assert campaign_row["status"] == "queued"
    assert campaign_row["total_recipients"] == 2
    assert campaign_row["queued_count"] == 2
    assert campaign_row["failed_count"] == 0

    sent_totals = db_session.execute(
        text(
            """
            SELECT total_messages_sent
            FROM sales_contacts
            WHERE id = ANY(CAST(:contact_ids AS uuid[]))
            ORDER BY phone_normalized ASC
            """
        ),
        {"contact_ids": [str(contact_one), str(contact_two)]},
    ).scalars().all()
    assert sent_totals == [1, 1]


def test_campaign_get_rejects_cross_tenant_row(db_session: Session) -> None:
    contact_id = SalesContactService(db_session).create_contact(
        current=current_two(),
        nome="Tenant Dois",
        telefone="(21) 99999-0000",
    )["id"]
    campaign = SalesCampaignService(db_session).create_campaign(
        current=current_two(),
        nome="Campanha Tenant Dois",
        conteudo="Ola",
        contact_ids=[str(contact_id)],
        idempotency_key="campaign:tenant-two",
    )

    with pytest.raises(HTTPException) as exc:
        SalesCampaignService(db_session).get_campaign(
            current=current_one(),
            campaign_id=str(campaign["id"]),
        )

    assert exc.value.status_code == 404


def create_contact(session: Session, *, nome: str, telefone: str) -> UUID:
    created = SalesContactService(session).create_contact(
        current=current_one(),
        nome=nome,
        telefone=telefone,
    )
    return UUID(str(created["id"]))


def create_channel(session: Session, *, tenant_id: UUID) -> UUID:
    row = session.execute(
        text(
            """
            INSERT INTO sales_channels (
                tenant_id, channel_type, name, status, config, webhook_secret
            )
            VALUES (
                :tenant_id, 'whatsapp_evolution', 'WhatsApp', 'conectado',
                '{}'::jsonb, 'secret'
            )
            RETURNING id
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().one()
    session.commit()
    return UUID(str(row["id"]))


def count_rows(session: Session, table_name: str) -> int:
    return session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
