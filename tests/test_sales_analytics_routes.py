from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.sales_analytics import get_sales_analytics_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.main import create_app

CONVERSATION_ID = UUID("55555555-5555-5555-5555-555555555555")
TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeSalesAnalyticsService:
    def __init__(self) -> None:
        self.current = None
        self.period = None
        self.limit = None

    def dashboard(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "mensagens_hoje": 3,
            "mensagens_semana": 10,
            "contatos_total": 5,
            "conversas_abertas": 2,
            "campanhas_ativas": 0,
            "taxa_resposta": 80.0,
        }

    def message_volume(self, **kwargs):
        self.current = kwargs["current"]
        self.period = kwargs["period"]
        return {
            "period": kwargs["period"],
            "data": [{"date": "2026-06-02", "enviadas": 2, "recebidas": 3}],
        }

    def recent_activity(self, **kwargs):
        self.current = kwargs["current"]
        self.limit = kwargs["limit"]
        return [
            {
                "tipo": "conversa",
                "titulo": "Paula",
                "descricao": "Oi",
                "canal": "whatsapp_evolution",
                "timestamp": datetime(2026, 6, 2, tzinfo=UTC),
                "link_id": CONVERSATION_ID,
                "status": "aberta",
                "aguardando_humano": True,
            }
        ]


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


def make_client(
    service: FakeSalesAnalyticsService | None = None,
    *,
    modules: tuple[str, ...] = ("sales",),
) -> tuple[TestClient, FakeSalesAnalyticsService]:
    fake_service = service or FakeSalesAnalyticsService()
    app = create_app()
    app.dependency_overrides[get_sales_analytics_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = lambda: make_current(modules=modules)
    return TestClient(app), fake_service


def test_flat_analytics_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/analytics/dashboard").status_code == 200
    messages = client.get("/api/v2/labby/analytics/messages", params={"period": "30d"})
    assert messages.status_code == 200
    assert messages.json()["period"] == "30d"
    assert service.period == "30d"
    activity = client.get("/api/v2/labby/analytics/activity", params={"limit": 8})
    assert activity.status_code == 200
    assert service.limit == 8


def test_canonical_sales_analytics_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/sales/analytics/dashboard").status_code == 200
    assert client.get("/api/v2/labby/sales/analytics/messages").status_code == 200
    assert client.get("/api/v2/labby/sales/analytics/activity").status_code == 200
    assert service.current.tenant_id == TENANT_ID


def test_analytics_router_requires_sales_module() -> None:
    client, _ = make_client(modules=("social_media",))

    response = client.get("/api/v2/labby/analytics/dashboard")

    assert response.status_code == 403
    assert response.json()["detail"] == "Modulo nao habilitado"
