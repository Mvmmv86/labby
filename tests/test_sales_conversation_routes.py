from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.sales_conversations import get_sales_conversation_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.main import create_app

CONVERSATION_ID = UUID("55555555-5555-5555-5555-555555555555")
CONTACT_ID = UUID("44444444-4444-4444-4444-444444444444")
CHANNEL_ID = UUID("66666666-6666-6666-6666-666666666666")
MESSAGE_ID = UUID("77777777-7777-7777-7777-777777777777")


class FakeSalesConversationService:
    def __init__(self) -> None:
        self.current = None
        self.updated_payload = None
        self.sent_payload = None

    def list_conversations(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "conversations": [make_conversation_list_item()],
            "total": 1,
            "page": kwargs["page"],
            "per_page": kwargs["per_page"],
            "pages": 1,
        }

    def notification_summary(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "transferencias_pendentes": 1,
            "total_nao_lidas": 2,
            "conversas_aguardando": [
                {
                    "id": CONVERSATION_ID,
                    "contato_nome": "Paula",
                    "channel_tipo": "whatsapp_evolution",
                    "ultima_mensagem": "Oi",
                    "ultima_mensagem_at": datetime(2026, 6, 2, tzinfo=UTC),
                    "mensagens_nao_lidas": 2,
                }
            ],
        }

    def get_conversation(self, **kwargs):
        self.current = kwargs["current"]
        return make_conversation_detail()

    def update_conversation(self, **kwargs):
        self.current = kwargs["current"]
        self.updated_payload = kwargs
        return make_conversation_mutation(message="Conversa atualizada")

    def list_messages(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "messages": [make_message()],
            "has_more": False,
            "next_cursor": None,
        }

    def mark_read(self, **kwargs):
        self.current = kwargs["current"]
        return {"marked": 2}

    def send_message(self, **kwargs):
        self.current = kwargs["current"]
        self.sent_payload = kwargs
        return make_message(direcao="saida", conteudo=kwargs["conteudo"], status="pending")

    def close_conversation(self, **kwargs):
        self.current = kwargs["current"]
        return make_conversation_mutation(status="fechada", message="Conversa fechada")


def make_current(modules: tuple[str, ...] = ("sales",)) -> CurrentMembership:
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
        membership_id=UUID("33333333-3333-3333-3333-333333333333"),
        email="admin@example.com",
        nome="Admin",
        role="admin",
        modules=modules,
    )


def make_conversation_list_item(**overrides):
    now = datetime(2026, 6, 2, tzinfo=UTC)
    row = {
        "id": CONVERSATION_ID,
        "contato_id": CONTACT_ID,
        "contato_nome": "Paula",
        "contato_telefone": "5511999990000",
        "channel_id": CHANNEL_ID,
        "channel_tipo": "whatsapp_evolution",
        "channel_nome": "WhatsApp",
        "status": "aberta",
        "assunto": "Venda",
        "tags": ["lead"],
        "atendente_id": None,
        "atendente_nome": None,
        "bot_ativo": False,
        "aguardando_humano": True,
        "ultima_mensagem": "Oi",
        "ultima_mensagem_at": now,
        "mensagens_nao_lidas": 1,
        "created_at": now,
    }
    row.update(overrides)
    return row


def make_conversation_detail(**overrides):
    now = datetime(2026, 6, 2, tzinfo=UTC)
    row = {
        "id": CONVERSATION_ID,
        "contato": {
            "id": CONTACT_ID,
            "nome": "Paula",
            "telefone": "5511999990000",
            "email": "paula@example.com",
            "tags": ["lead"],
            "grupo": "Leads",
            "notas": "Contato quente",
            "ultima_interacao": now,
            "created_at": now,
        },
        "channel": {"id": CHANNEL_ID, "tipo": "whatsapp_evolution", "nome": "WhatsApp"},
        "status": "aberta",
        "assunto": "Venda",
        "tags": ["lead"],
        "atendente_id": None,
        "atendente_nome": None,
        "bot_ativo": False,
        "ultima_mensagem_at": now,
        "fechado_at": None,
        "created_at": now,
    }
    row.update(overrides)
    return row


def make_message(**overrides):
    now = datetime(2026, 6, 2, tzinfo=UTC)
    row = {
        "id": MESSAGE_ID,
        "conversa_id": CONVERSATION_ID,
        "contato_id": CONTACT_ID,
        "direcao": "entrada",
        "remetente_tipo": "contato",
        "remetente_id": None,
        "tipo": "text",
        "conteudo": "Oi",
        "media_url": None,
        "media_caption": None,
        "status": "sent",
        "created_at": now,
    }
    row.update(overrides)
    return row


def make_conversation_mutation(**overrides):
    row = {
        "id": CONVERSATION_ID,
        "status": "aberta",
        "atendente_id": None,
        "assunto": "Venda",
        "tags": ["lead"],
        "message": "Conversa atualizada",
    }
    row.update(overrides)
    return row


def make_client(
    service: FakeSalesConversationService | None = None,
    *,
    modules: tuple[str, ...] = ("sales",),
) -> tuple[TestClient, FakeSalesConversationService]:
    fake_service = service or FakeSalesConversationService()
    app = create_app()
    app.dependency_overrides[get_sales_conversation_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = lambda: make_current(modules=modules)
    return TestClient(app), fake_service


def test_flat_conversation_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/conversations/").status_code == 200
    assert client.get("/api/v2/labby/conversations/notifications/summary").status_code == 200
    assert client.get(f"/api/v2/labby/conversations/{CONVERSATION_ID}").status_code == 200
    assert (
        client.get(f"/api/v2/labby/conversations/{CONVERSATION_ID}/messages").status_code
        == 200
    )
    assert (
        client.post(f"/api/v2/labby/conversations/{CONVERSATION_ID}/mark-read").status_code
        == 200
    )
    send = client.post(
        f"/api/v2/labby/conversations/{CONVERSATION_ID}/messages",
        json={"conteudo": "Resposta", "tipo": "text"},
    )
    assert send.status_code == 201
    assert service.sent_payload["conteudo"] == "Resposta"
    assert (
        client.put(
            f"/api/v2/labby/conversations/{CONVERSATION_ID}",
            json={"status": "pendente", "tags": ["vip"]},
        ).status_code
        == 200
    )
    assert service.updated_payload["patch"] == {"status": "pendente", "tags": ["vip"]}
    assert client.post(f"/api/v2/labby/conversations/{CONVERSATION_ID}/close").status_code == 200


def test_canonical_sales_conversation_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/sales/conversations/").status_code == 200
    assert (
        client.get("/api/v2/labby/sales/conversations/notifications/summary").status_code
        == 200
    )
    assert (
        client.get(f"/api/v2/labby/sales/conversations/{CONVERSATION_ID}").status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v2/labby/sales/conversations/{CONVERSATION_ID}/messages",
            json={"conteudo": "Resposta"},
        ).status_code
        == 201
    )
    assert service.current.tenant_id == UUID("22222222-2222-2222-2222-222222222222")


def test_conversations_router_requires_sales_module() -> None:
    client, _ = make_client(modules=("social_media",))

    response = client.get("/api/v2/labby/conversations/")

    assert response.status_code == 403
    assert response.json()["detail"] == "Modulo nao habilitado"
