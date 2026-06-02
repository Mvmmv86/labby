from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.sales_channels import get_sales_channel_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.main import create_app

CHANNEL_ID = UUID("66666666-6666-6666-6666-666666666666")
TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeSalesChannelService:
    def __init__(self) -> None:
        self.current = None
        self.created_payload = None
        self.updated_payload = None
        self.connected_payload = None

    def list_channels(self, **kwargs):
        self.current = kwargs["current"]
        return {"channels": [make_channel()]}

    def create_channel(self, **kwargs):
        self.current = kwargs["current"]
        self.created_payload = kwargs
        return make_channel(tipo=kwargs["tipo"], nome=kwargs["nome"])

    def get_channel(self, **kwargs):
        self.current = kwargs["current"]
        return make_channel()

    def update_channel(self, **kwargs):
        self.current = kwargs["current"]
        self.updated_payload = kwargs
        return make_channel(nome=kwargs["patch"].get("nome", "WhatsApp"))

    def delete_channel(self, **kwargs):
        self.current = kwargs["current"]
        return {"id": CHANNEL_ID, "message": "Canal removido com sucesso"}

    def channel_status(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "id": CHANNEL_ID,
            "tipo": "whatsapp_evolution",
            "nome": "WhatsApp",
            "status": "conectado",
            "numero": "5511999990000",
            "phone_number": "5511999990000",
            "bot_username": None,
            "guild_name": None,
            "widget_id": None,
            "config": None,
            "ultimo_evento_at": datetime(2026, 6, 2, tzinfo=UTC),
        }

    async def connect_channel(self, **kwargs):
        self.current = kwargs["current"]
        self.connected_payload = kwargs
        return {
            "status": "conectando",
            "qr_code": "",
            "instance_name": "labby_test",
            "message": "Escaneie o QR code com seu WhatsApp.",
        }

    def disconnect_channel(self, **kwargs):
        self.current = kwargs["current"]
        return {"status": "desconectado", "message": "Canal WhatsApp desconectado"}


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


def make_channel(**overrides):
    now = datetime(2026, 6, 2, tzinfo=UTC)
    row = {
        "id": CHANNEL_ID,
        "tenant_id": TENANT_ID,
        "tipo": "whatsapp_evolution",
        "nome": "WhatsApp",
        "status": "conectado",
        "config": {"phone_number": "5511999990000"},
        "webhook_configured": True,
        "ultimo_evento_at": now,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_client(
    service: FakeSalesChannelService | None = None,
    *,
    modules: tuple[str, ...] = ("sales",),
) -> tuple[TestClient, FakeSalesChannelService]:
    fake_service = service or FakeSalesChannelService()
    app = create_app()
    app.dependency_overrides[get_sales_channel_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = lambda: make_current(modules=modules)
    return TestClient(app), fake_service


def test_flat_channel_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/channels/").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/channels/",
            json={"tipo": "whatsapp_evolution", "nome": "WhatsApp"},
        ).status_code
        == 201
    )
    assert service.created_payload["tipo"] == "whatsapp_evolution"
    assert client.get(f"/api/v2/labby/channels/{CHANNEL_ID}").status_code == 200
    assert (
        client.put(
            f"/api/v2/labby/channels/{CHANNEL_ID}",
            json={"nome": "WhatsApp Comercial"},
        ).status_code
        == 200
    )
    assert service.updated_payload["patch"] == {"nome": "WhatsApp Comercial"}
    assert client.get(f"/api/v2/labby/channels/{CHANNEL_ID}/status").status_code == 200
    assert client.post(f"/api/v2/labby/channels/{CHANNEL_ID}/connect", json={}).status_code == 200
    assert (
        client.post(f"/api/v2/labby/channels/{CHANNEL_ID}/disconnect", json={}).status_code
        == 200
    )
    assert client.delete(f"/api/v2/labby/channels/{CHANNEL_ID}").status_code == 200


def test_canonical_sales_channel_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/sales/channels/").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/sales/channels/",
            json={"tipo": "web_chatbot", "nome": "Web Chat"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/v2/labby/sales/channels/{CHANNEL_ID}/connect",
            json={"greeting": "Ola"},
        ).status_code
        == 200
    )
    assert service.connected_payload["data"] == {"greeting": "Ola"}
    assert service.current.tenant_id == TENANT_ID


def test_channels_router_requires_sales_module() -> None:
    client, _ = make_client(modules=("social_media",))

    response = client.get("/api/v2/labby/channels/")

    assert response.status_code == 403
    assert response.json()["detail"] == "Modulo nao habilitado"
