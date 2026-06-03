import json
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domains.sales.bot_service import SalesBotService
from app.domains.sales.widget_service import (
    WIDGET_MESSAGE_LIMIT_PER_IP_PER_MINUTE,
    PublicWidgetService,
)
from tests.test_sales_contacts_integration import TENANT_1, TENANT_2, current_one, current_two
from tests.test_sales_contacts_integration import (
    db_session as _db_session_fixture,  # noqa: F401
)
from tests.test_sales_contacts_integration import (
    migrated_engine as _migrated_engine_fixture,  # noqa: F401
)

pytestmark = pytest.mark.integration


def test_sales_bot_crud_and_cross_tenant_scope_hit_real_postgres(
    db_session: Session,
) -> None:
    db_session.execute(
        text("UPDATE tenants SET plano = 'pro' WHERE id = :tenant_id"),
        {"tenant_id": TENANT_1},
    )
    db_session.commit()
    channel_one = create_web_widget_channel(
        db_session,
        tenant_id=TENANT_1,
        widget_id="labby_widget_bot_crud_one",
    )
    channel_two = create_web_widget_channel(
        db_session,
        tenant_id=TENANT_2,
        widget_id="labby_widget_bot_crud_two",
    )
    service = SalesBotService(db_session)

    created = service.create_bot(
        current=current_one(),
        nome="Bot Lead",
        descricao="Atendimento inicial",
        fallback_message="Um atendente respondera em breve.",
        faqs=[{"pergunta": "preco", "resposta": "Chamaremos voce."}],
        channel_ids=[str(channel_one)],
    )

    assert created["ativo"] is False
    assert created["channel_ids"] == [channel_one]
    toggled = service.toggle_bot(current=current_one(), bot_id=str(created["id"]))
    assert toggled["ativo"] is True

    updated = service.update_bot(
        current=current_one(),
        bot_id=str(created["id"]),
        patch={"nome": "Bot Comercial", "ativo": False},
    )
    assert updated["nome"] == "Bot Comercial"
    assert updated["ativo"] is False

    copied = service.duplicate_bot(current=current_one(), bot_id=str(created["id"]))
    assert copied["nome"] == "Bot Comercial (copia)"
    assert copied["ativo"] is False
    service.delete_bot(current=current_one(), bot_id=str(copied["id"]))

    other = service.create_bot(
        current=current_two(),
        nome="Bot Tenant Dois",
        channel_ids=[str(channel_two)],
    )
    with pytest.raises(HTTPException) as exc:
        service.get_bot(current=current_one(), bot_id=str(other["id"]))
    assert exc.value.status_code == 404


def test_public_widget_ingests_messages_idempotently_and_runs_bot(
    db_session: Session,
) -> None:
    channel_id = create_web_widget_channel(
        db_session,
        tenant_id=TENANT_1,
        widget_id="labby_widget_runtime",
    )
    bot = SalesBotService(db_session).create_bot(
        current=current_one(),
        nome="Bot Preco",
        fallback_message="Um atendente vai responder.",
        faqs=[{"pergunta": "preco", "resposta": "O plano comeca em R$ 99."}],
        channel_ids=[str(channel_id)],
    )
    SalesBotService(db_session).toggle_bot(current=current_one(), bot_id=str(bot["id"]))
    service = PublicWidgetService(db_session)

    first = service.receive_message(
        widget_id="labby_widget_runtime",
        visitor_id="visitor-1",
        visitor_name="Paula",
        message="Quero saber o preco",
        client_message_id="client-msg-1",
        client_ip="127.0.0.1",
    )
    duplicate = service.receive_message(
        widget_id="labby_widget_runtime",
        visitor_id="visitor-1",
        visitor_name="Paula",
        message="Quero saber o preco",
        client_message_id="client-msg-1",
        client_ip="127.0.0.1",
    )

    assert first["duplicate"] is False
    assert first["bot_response"] == "O plano comeca em R$ 99."
    assert duplicate["duplicate"] is True
    assert duplicate["message_id"] == first["message_id"]
    assert count_rows(db_session, "sales_contacts") == 1
    assert count_rows(db_session, "sales_conversations") == 1
    assert count_rows(db_session, "sales_messages") == 2
    assert count_rows(db_session, "sales_bot_runs") == 1

    contact = db_session.execute(
        text(
            """
            SELECT total_messages_received, total_messages_sent
            FROM sales_contacts
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": TENANT_1},
    ).mappings().one()
    assert contact["total_messages_received"] == 1
    assert contact["total_messages_sent"] == 1

    conversation = db_session.execute(
        text(
            """
            SELECT bot_active, waiting_for_human, bot_id
            FROM sales_conversations
            WHERE tenant_id = :tenant_id
            """
        ),
        {"tenant_id": TENANT_1},
    ).mappings().one()
    assert conversation["bot_active"] is True
    assert conversation["waiting_for_human"] is False
    assert conversation["bot_id"] == bot["id"]

    listed = service.list_messages(
        widget_id="labby_widget_runtime",
        visitor_id="visitor-1",
        after=None,
        client_ip="127.0.0.1",
    )
    assert [message["direction"] for message in listed["messages"]] == ["entrada", "saida"]


def test_public_widget_rejects_origin_when_channel_has_allowlist(
    db_session: Session,
) -> None:
    create_web_widget_channel(
        db_session,
        tenant_id=TENANT_1,
        widget_id="labby_widget_origin",
        config={"allowed_origins": ["https://cliente.example"]},
    )

    service = PublicWidgetService(db_session)
    assert service.config(
        widget_id="labby_widget_origin",
        origin="https://cliente.example",
    )["active"]
    with pytest.raises(HTTPException) as exc:
        service.config(
            widget_id="labby_widget_origin",
            origin="https://evil.example",
        )
    assert exc.value.status_code == 403


def test_public_widget_message_rate_limit_uses_ip_not_visitor_id(
    db_session: Session,
) -> None:
    create_web_widget_channel(
        db_session,
        tenant_id=TENANT_1,
        widget_id="labby_widget_rate_limit",
    )
    service = PublicWidgetService(db_session)

    for index in range(WIDGET_MESSAGE_LIMIT_PER_IP_PER_MINUTE):
        result = service.receive_message(
            widget_id="labby_widget_rate_limit",
            visitor_id=f"visitor-{index}",
            visitor_name="Paula",
            message=f"Mensagem {index}",
            client_message_id=f"client-message-{index}",
            client_ip="203.0.113.10",
        )
        assert result["status"] == "ok"

    with pytest.raises(HTTPException) as exc:
        service.receive_message(
            widget_id="labby_widget_rate_limit",
            visitor_id="visitor-rotated",
            visitor_name="Paula",
            message="Tentativa acima do limite",
            client_message_id="client-message-over-limit",
            client_ip="203.0.113.10",
        )
    assert exc.value.status_code == 429

    blocked = db_session.execute(
        text(
            """
            SELECT metadata_json
            FROM rate_limit_events
            WHERE tenant_id = :tenant_id
              AND provider = 'web_widget'
              AND action = 'widget.message.ip'
              AND outcome = 'blocked'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"tenant_id": TENANT_1},
    ).mappings().one()
    assert blocked["metadata_json"]["client_ip"] == "203.0.113.10"


def create_web_widget_channel(
    session: Session,
    *,
    tenant_id: UUID,
    widget_id: str,
    config: dict | None = None,
) -> UUID:
    widget_config = {
        "widget_id": widget_id,
        "active": True,
        "color": "#00d4aa",
        "greeting": "Ola! Como posso ajudar?",
        "position": "bottom-right",
    }
    widget_config.update(config or {})
    row = session.execute(
        text(
            """
            INSERT INTO sales_channels (
                tenant_id, channel_type, name, status, config, webhook_secret
            )
            VALUES (
                :tenant_id, 'web_chatbot', 'Web Chat', 'conectado',
                CAST(:config AS jsonb), 'widget-secret'
            )
            RETURNING id
            """
        ),
        {"tenant_id": tenant_id, "config": json_dumps(widget_config)},
    ).mappings().one()
    session.commit()
    return UUID(str(row["id"]))


def json_dumps(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False)


def count_rows(session: Session, table_name: str) -> int:
    return session.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
