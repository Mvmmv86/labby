from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domains.sales.contact_service import SalesContactService
from app.domains.sales.conversation_service import SalesConversationService
from tests.test_sales_contacts_integration import (
    MEMBERSHIP_1,
    MEMBERSHIP_2,
    TENANT_1,
    TENANT_2,
    current_one,
    current_two,
)
from tests.test_sales_contacts_integration import (
    db_session as _db_session_fixture,  # noqa: F401
)
from tests.test_sales_contacts_integration import (
    migrated_engine as _migrated_engine_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


def create_contact(
    session: Session,
    *,
    tenant_current,
    nome: str,
    telefone: str,
) -> UUID:
    created = SalesContactService(session).create_contact(
        current=tenant_current,
        nome=nome,
        telefone=telefone,
    )
    return UUID(str(created["id"]))


def create_channel(
    session: Session,
    *,
    tenant_id: UUID,
    channel_type: str = "whatsapp_evolution",
    status: str = "conectado",
) -> UUID:
    row = session.execute(
        text(
            """
            INSERT INTO sales_channels (tenant_id, channel_type, name, status, config)
            VALUES (:tenant_id, :channel_type, 'WhatsApp', :status, '{}'::jsonb)
            RETURNING id
            """
        ),
        {"tenant_id": tenant_id, "channel_type": channel_type, "status": status},
    ).mappings().one()
    session.commit()
    return UUID(str(row["id"]))


def create_conversation(
    session: Session,
    *,
    tenant_id: UUID,
    contact_id: UUID,
    channel_id: UUID | None = None,
    waiting_for_human: bool = True,
    membership_id: UUID = MEMBERSHIP_1,
) -> UUID:
    row = session.execute(
        text(
            """
            INSERT INTO sales_conversations (
                tenant_id, contact_id, channel_id, subject, tags, waiting_for_human,
                created_by_membership_id, updated_by_membership_id, last_message_at
            )
            VALUES (
                :tenant_id, :contact_id, :channel_id, 'Venda', '["lead"]'::jsonb,
                :waiting_for_human, :membership_id, :membership_id, :last_message_at
            )
            RETURNING id
            """
        ),
        {
            "tenant_id": tenant_id,
            "contact_id": contact_id,
            "channel_id": channel_id,
            "waiting_for_human": waiting_for_human,
            "membership_id": membership_id,
            "last_message_at": datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        },
    ).mappings().one()
    session.commit()
    return UUID(str(row["id"]))


def create_message(
    session: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    contact_id: UUID,
    direction: str,
    content: str,
    status: str = "sent",
    created_at: datetime | None = None,
) -> UUID:
    row = session.execute(
        text(
            """
            INSERT INTO sales_messages (
                tenant_id, conversation_id, contact_id, direction, sender_type,
                message_type, content, status, created_at
            )
            VALUES (
                :tenant_id, :conversation_id, :contact_id, :direction,
                CASE WHEN :direction = 'entrada' THEN 'contato' ELSE 'usuario' END,
                'text', :content, :status, :created_at
            )
            RETURNING id
            """
        ),
        {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "contact_id": contact_id,
            "direction": direction,
            "content": content,
            "status": status,
            "created_at": created_at or datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
        },
    ).mappings().one()
    session.commit()
    return UUID(str(row["id"]))


def test_sales_inbox_list_summary_and_contact_aggregates_hit_real_postgres(
    db_session: Session,
) -> None:
    contact_id = create_contact(
        db_session,
        tenant_current=current_one(),
        nome="Paula",
        telefone="(11) 99999-0000",
    )
    channel_id = create_channel(db_session, tenant_id=TENANT_1)
    conversation_id = create_conversation(
        db_session,
        tenant_id=TENANT_1,
        contact_id=contact_id,
        channel_id=channel_id,
    )
    create_message(
        db_session,
        tenant_id=TENANT_1,
        conversation_id=conversation_id,
        contact_id=contact_id,
        direction="entrada",
        content="Preciso de ajuda",
        status="sent",
        created_at=datetime(2026, 6, 2, 12, 1, tzinfo=UTC),
    )

    conversation_service = SalesConversationService(db_session)
    contact_service = SalesContactService(db_session)

    listed = conversation_service.list_conversations(current=current_one())
    assert listed["total"] == 1
    assert listed["conversations"][0]["id"] == conversation_id
    assert listed["conversations"][0]["ultima_mensagem"] == "Preciso de ajuda"
    assert listed["conversations"][0]["mensagens_nao_lidas"] == 1

    summary = conversation_service.notification_summary(current=current_one())
    assert summary["transferencias_pendentes"] == 1
    assert summary["total_nao_lidas"] == 1
    assert summary["conversas_aguardando"][0]["id"] == conversation_id

    contacts = contact_service.list_contacts(current=current_one())
    assert contacts["contacts"][0]["total_conversas"] == 1
    assert contacts["contacts"][0]["canais_vinculados"] == ["whatsapp_evolution"]

    detail = contact_service.get_contact(current=current_one(), contact_id=str(contact_id))
    assert detail["total_conversas"] == 1
    assert detail["conversas_recentes"][0]["id"] == conversation_id


def test_sales_inbox_notification_summary_counts_beyond_preview_limit(
    db_session: Session,
) -> None:
    contact_id = create_contact(
        db_session,
        tenant_current=current_one(),
        nome="Paula",
        telefone="(11) 99999-0000",
    )

    for _ in range(55):
        create_conversation(
            db_session,
            tenant_id=TENANT_1,
            contact_id=contact_id,
            waiting_for_human=True,
        )

    summary = SalesConversationService(db_session).notification_summary(current=current_one())

    assert summary["transferencias_pendentes"] == 55
    assert len(summary["conversas_aguardando"]) == 50


def test_sales_inbox_messages_mark_read_and_send_update_real_rows(
    db_session: Session,
) -> None:
    contact_id = create_contact(
        db_session,
        tenant_current=current_one(),
        nome="Paula",
        telefone="(11) 99999-0000",
    )
    conversation_id = create_conversation(
        db_session,
        tenant_id=TENANT_1,
        contact_id=contact_id,
        waiting_for_human=True,
    )
    older = create_message(
        db_session,
        tenant_id=TENANT_1,
        conversation_id=conversation_id,
        contact_id=contact_id,
        direction="entrada",
        content="Mensagem antiga",
        status="sent",
        created_at=datetime(2026, 6, 2, 12, 0, tzinfo=UTC),
    )
    create_message(
        db_session,
        tenant_id=TENANT_1,
        conversation_id=conversation_id,
        contact_id=contact_id,
        direction="entrada",
        content="Mensagem nova",
        status="sent",
        created_at=datetime(2026, 6, 2, 12, 1, tzinfo=UTC),
    )

    service = SalesConversationService(db_session)

    page = service.list_messages(
        current=current_one(),
        conversation_id=str(conversation_id),
        limit=1,
    )
    assert page["messages"][0]["conteudo"] == "Mensagem nova"
    assert page["has_more"] is True
    assert page["next_cursor"] is not None

    next_page = service.list_messages(
        current=current_one(),
        conversation_id=str(conversation_id),
        cursor=str(page["next_cursor"]),
        limit=1,
    )
    assert next_page["messages"][0]["id"] == older

    marked = service.mark_read(current=current_one(), conversation_id=str(conversation_id))
    assert marked["marked"] == 2

    sent = service.send_message(
        current=current_one(),
        conversation_id=str(conversation_id),
        conteudo="Resposta humana",
    )
    assert sent["direcao"] == "saida"
    assert sent["status"] == "pending"

    row = db_session.execute(
        text(
            """
            SELECT
                c.waiting_for_human,
                sc.total_messages_sent,
                sc.last_interaction_at
            FROM sales_conversations c
            JOIN sales_contacts sc ON sc.id = c.contact_id
            WHERE c.id = :conversation_id
            """
        ),
        {"conversation_id": conversation_id},
    ).mappings().one()
    assert row["waiting_for_human"] is False
    assert row["total_messages_sent"] == 1
    assert row["last_interaction_at"] is not None

    closed = service.close_conversation(current=current_one(), conversation_id=str(conversation_id))
    assert closed["status"] == "fechada"


def test_sales_inbox_cross_tenant_lookup_returns_404_for_real_row(
    db_session: Session,
) -> None:
    contact_id = create_contact(
        db_session,
        tenant_current=current_two(),
        nome="Contato Tenant Dois",
        telefone="(21) 99999-0000",
    )
    conversation_id = create_conversation(
        db_session,
        tenant_id=TENANT_2,
        contact_id=contact_id,
        waiting_for_human=False,
        membership_id=MEMBERSHIP_2,
    )

    service = SalesConversationService(db_session)

    with pytest.raises(HTTPException) as exc:
        service.get_conversation(current=current_one(), conversation_id=str(conversation_id))

    assert exc.value.status_code == 404


def test_sales_inbox_message_external_id_unique_per_tenant_provider(
    db_session: Session,
) -> None:
    contact_id = create_contact(
        db_session,
        tenant_current=current_one(),
        nome="Paula",
        telefone="(11) 99999-0000",
    )
    conversation_id = create_conversation(
        db_session,
        tenant_id=TENANT_1,
        contact_id=contact_id,
        waiting_for_human=False,
    )
    created_at = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

    db_session.execute(
        text(
            """
            INSERT INTO sales_messages (
                tenant_id, conversation_id, contact_id, direction, sender_type,
                message_type, content, status, provider, external_id, created_at
            )
            VALUES
                (
                    :tenant_id, :conversation_id, :contact_id, 'entrada', 'contato',
                    'text', 'Primeira', 'sent', 'evolution', 'wa-1', :created_at
                ),
                (
                    :tenant_id, :conversation_id, :contact_id, 'entrada', 'contato',
                    'text', 'Segunda', 'sent', 'evolution', 'wa-1',
                    :second_created_at
                )
            ON CONFLICT (tenant_id, provider, external_id)
                WHERE provider IS NOT NULL AND external_id IS NOT NULL
            DO NOTHING
            """
        ),
        {
            "tenant_id": TENANT_1,
            "conversation_id": conversation_id,
            "contact_id": contact_id,
            "created_at": created_at,
            "second_created_at": created_at + timedelta(seconds=1),
        },
    )
    db_session.commit()

    count = db_session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM sales_messages
            WHERE tenant_id = :tenant_id
              AND provider = 'evolution'
              AND external_id = 'wa-1'
            """
        ),
        {"tenant_id": TENANT_1},
    ).scalar_one()
    assert count == 1
