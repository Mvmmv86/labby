from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.sales_bots import get_sales_bot_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.main import create_app

BOT_ID = UUID("12121212-1212-1212-1212-121212121212")
CHANNEL_ID = UUID("66666666-6666-6666-6666-666666666666")
TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeSalesBotService:
    def __init__(self) -> None:
        self.current = None
        self.created_payload = None
        self.updated_payload = None
        self.toggled_bot_id = None
        self.duplicated_bot_id = None

    def list_bots(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "bots": [make_bot_list_item()],
            "total": 1,
            "page": kwargs["page"],
            "per_page": kwargs["per_page"],
            "pages": 1,
        }

    def get_bot(self, **kwargs):
        self.current = kwargs["current"]
        return make_bot_detail()

    def create_bot(self, **kwargs):
        self.current = kwargs["current"]
        self.created_payload = kwargs
        return make_bot_detail(nome=kwargs["nome"])

    def update_bot(self, **kwargs):
        self.current = kwargs["current"]
        self.updated_payload = kwargs
        return make_bot_detail(nome=kwargs["patch"].get("nome", "Bot Lead"))

    def delete_bot(self, **kwargs):
        self.current = kwargs["current"]
        return {"id": BOT_ID, "message": "Bot removido com sucesso"}

    def toggle_bot(self, **kwargs):
        self.current = kwargs["current"]
        self.toggled_bot_id = kwargs["bot_id"]
        return {"id": BOT_ID, "nome": "Bot Lead", "ativo": True, "message": "Bot ativado"}

    def duplicate_bot(self, **kwargs):
        self.current = kwargs["current"]
        self.duplicated_bot_id = kwargs["bot_id"]
        return make_bot_detail(id=UUID("34343434-3434-3434-3434-343434343434"))


def make_current(modules: tuple[str, ...] = ("sales",)) -> CurrentMembership:
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=TENANT_ID,
        membership_id=UUID("33333333-3333-3333-3333-333333333333"),
        email="admin@example.com",
        nome="Admin",
        role="admin",
        modules=modules,
    )


def make_bot_list_item(**overrides):
    now = datetime(2026, 6, 3, tzinfo=UTC)
    row = {
        "id": BOT_ID,
        "nome": "Bot Lead",
        "descricao": "Atendimento inicial",
        "modelo": "gpt-4o-mini",
        "tipo_trigger": "todas_mensagens",
        "ativo": False,
        "total_acionamentos": 0,
        "total_concluidos": 0,
        "total_transferidos": 0,
        "channel_ids": [CHANNEL_ID],
        "created_at": now,
    }
    row.update(overrides)
    return row


def make_bot_detail(**overrides):
    row = make_bot_list_item()
    row.update(
        {
            "system_prompt": "Seja cordial",
            "welcome_message": "Ola!",
            "fallback_message": "Um atendente vai responder.",
            "base_conhecimento": "FAQ",
            "faqs": [{"pergunta": "preco", "resposta": "Chamaremos voce."}],
            "temperatura": 0.3,
            "max_tokens": 800,
            "trigger_valor": None,
            "criado_por": UUID("33333333-3333-3333-3333-333333333333"),
            "updated_at": datetime(2026, 6, 3, tzinfo=UTC),
        }
    )
    row.update(overrides)
    return row


def make_client(
    service: FakeSalesBotService | None = None,
    *,
    modules: tuple[str, ...] = ("sales",),
) -> tuple[TestClient, FakeSalesBotService]:
    fake_service = service or FakeSalesBotService()
    app = create_app()
    app.dependency_overrides[get_sales_bot_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = lambda: make_current(modules=modules)
    return TestClient(app), fake_service


def test_flat_bot_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/bots/").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/bots/",
            json={
                "nome": "Bot Lead",
                "system_prompt": "Seja cordial",
                "channel_ids": [str(CHANNEL_ID)],
            },
        ).status_code
        == 201
    )
    assert service.created_payload["channel_ids"] == [str(CHANNEL_ID)]
    assert client.get(f"/api/v2/labby/bots/{BOT_ID}").status_code == 200
    assert (
        client.put(
            f"/api/v2/labby/bots/{BOT_ID}",
            json={"nome": "Bot Lead 2", "campo_legacy": "ignorado"},
        ).status_code
        == 200
    )
    assert service.updated_payload["patch"] == {"nome": "Bot Lead 2"}
    assert client.post(f"/api/v2/labby/bots/{BOT_ID}/toggle").status_code == 200
    assert service.toggled_bot_id == str(BOT_ID)
    assert client.post(f"/api/v2/labby/bots/{BOT_ID}/duplicate").status_code == 201
    assert service.duplicated_bot_id == str(BOT_ID)
    assert client.delete(f"/api/v2/labby/bots/{BOT_ID}").status_code == 200


def test_canonical_sales_bot_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/sales/bots/").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/sales/bots/",
            json={"nome": "Bot", "tipo_trigger": "keyword", "trigger_valor": "preco"},
        ).status_code
        == 201
    )
    assert client.get(f"/api/v2/labby/sales/bots/{BOT_ID}").status_code == 200
    assert client.post(f"/api/v2/labby/sales/bots/{BOT_ID}/toggle").status_code == 200
    assert service.current.tenant_id == TENANT_ID


def test_bots_router_requires_sales_module() -> None:
    client, _ = make_client(modules=("social_media",))

    response = client.get("/api/v2/labby/bots/")

    assert response.status_code == 403
    assert response.json()["detail"] == "Modulo nao habilitado"
