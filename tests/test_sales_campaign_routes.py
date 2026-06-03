from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.sales_campaigns import get_sales_campaign_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.main import create_app

CAMPAIGN_ID = UUID("77777777-7777-7777-7777-777777777777")
CONTACT_ID = UUID("44444444-4444-4444-4444-444444444444")
JOB_ID = UUID("99999999-9999-9999-9999-999999999999")
TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")


class FakeSalesCampaignService:
    def __init__(self) -> None:
        self.current = None
        self.created_payload = None
        self.updated_payload = None
        self.add_recipients_payload = None
        self.dispatch_payload = None
        self.preview_campaign_id = None
        self.started_campaign_id = None
        self.cancelled_campaign_id = None

    def list_campaigns(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "campaigns": [make_campaign_list_item()],
            "total": 1,
            "page": kwargs["page"],
            "per_page": kwargs["per_page"],
            "pages": 1,
        }

    def get_campaign(self, **kwargs):
        self.current = kwargs["current"]
        return make_campaign_detail()

    def create_campaign(self, **kwargs):
        self.current = kwargs["current"]
        self.created_payload = kwargs
        return make_campaign_mutation(message="Campanha criada")

    def update_campaign(self, **kwargs):
        self.current = kwargs["current"]
        self.updated_payload = kwargs
        return make_campaign_mutation(message="Campanha atualizada")

    def delete_campaign(self, **kwargs):
        self.current = kwargs["current"]
        return {"id": CAMPAIGN_ID, "message": "Campanha removida"}

    def list_recipients(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "recipients": [make_recipient()],
            "total": 1,
            "page": kwargs["page"],
            "per_page": kwargs["per_page"],
            "pages": 1,
        }

    def add_recipients(self, **kwargs):
        self.current = kwargs["current"]
        self.add_recipients_payload = kwargs
        return {
            "campaign_id": CAMPAIGN_ID,
            "requested": 1,
            "inserted": 1,
            "duplicates": 0,
            "invalid_or_optout": 0,
            "total_destinatarios": 1,
        }

    def preview_recipients(self, **kwargs):
        self.current = kwargs["current"]
        self.preview_campaign_id = kwargs["campaign_id"]
        return {
            "contacts": [
                {
                    "id": CONTACT_ID,
                    "nome": "Paula",
                    "telefone": "5511999990000",
                    "email": "paula@example.com",
                    "grupo": "Leads",
                }
            ],
            "total": 1,
        }

    def start_campaign(self, **kwargs):
        self.current = kwargs["current"]
        self.started_campaign_id = kwargs["campaign_id"]
        return make_campaign_mutation(status="ativa", message="Campanha iniciada")

    def cancel_campaign(self, **kwargs):
        self.current = kwargs["current"]
        self.cancelled_campaign_id = kwargs["campaign_id"]
        return make_campaign_mutation(status="cancelled", message="Campanha cancelada")

    def dispatch_campaign(self, **kwargs):
        self.current = kwargs["current"]
        self.dispatch_payload = kwargs
        return {
            "campaign_id": CAMPAIGN_ID,
            "status": "sending",
            "job_id": JOB_ID,
            "job_type": "sales.campaign.dispatch",
            "idempotency_key": "sales.campaign.dispatch:test",
            "duplicate": False,
        }


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


def make_campaign_list_item(**overrides):
    now = datetime(2026, 6, 2, tzinfo=UTC)
    row = {
        "id": CAMPAIGN_ID,
        "nome": "Promo Junho",
        "status": "draft",
        "channel_id": None,
        "channel_tipo": None,
        "total_destinatarios": 1,
        "queued_count": 0,
        "sent_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "scheduled_at": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_campaign_detail(**overrides):
    row = make_campaign_list_item()
    row.update(
        {
            "descricao": "Oferta",
            "conteudo": "Ola, temos uma oferta",
            "tipo_mensagem": "text",
            "idempotency_key": "campaign:test",
            "started_at": None,
            "finished_at": None,
        }
    )
    row.update(overrides)
    return row


def make_campaign_mutation(**overrides):
    row = {
        "id": CAMPAIGN_ID,
        "nome": "Promo Junho",
        "status": "draft",
        "total_destinatarios": 1,
        "message": "Campanha atualizada",
    }
    row.update(overrides)
    return row


def make_recipient(**overrides):
    now = datetime(2026, 6, 2, tzinfo=UTC)
    row = {
        "id": UUID("88888888-8888-8888-8888-888888888888"),
        "campaign_id": CAMPAIGN_ID,
        "contact_id": CONTACT_ID,
        "contato_nome": "Paula",
        "telefone": "5511999990000",
        "status": "pending",
        "message_id": None,
        "conversation_id": None,
        "error": None,
        "queued_at": None,
        "created_at": now,
    }
    row.update(overrides)
    return row


def make_client(
    service: FakeSalesCampaignService | None = None,
    *,
    modules: tuple[str, ...] = ("sales",),
) -> tuple[TestClient, FakeSalesCampaignService]:
    fake_service = service or FakeSalesCampaignService()
    app = create_app()
    app.dependency_overrides[get_sales_campaign_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = lambda: make_current(modules=modules)
    return TestClient(app), fake_service


def test_flat_campaign_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/campaigns/").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/campaigns/",
            json={
                "nome": "Promo Junho",
                "conteudo": "Ola",
                "contact_ids": [str(CONTACT_ID)],
            },
        ).status_code
        == 201
    )
    assert service.created_payload["nome"] == "Promo Junho"
    assert client.get(f"/api/v2/labby/campaigns/{CAMPAIGN_ID}").status_code == 200
    assert (
        client.put(
            f"/api/v2/labby/campaigns/{CAMPAIGN_ID}",
            json={"nome": "Promo Julho"},
        ).status_code
        == 200
    )
    assert service.updated_payload["patch"] == {"nome": "Promo Julho"}
    assert client.get(f"/api/v2/labby/campaigns/{CAMPAIGN_ID}/recipients").status_code == 200
    assert (
        client.post(
            f"/api/v2/labby/campaigns/{CAMPAIGN_ID}/recipients",
            json={"contact_ids": [str(CONTACT_ID)]},
        ).status_code
        == 200
    )
    assert service.add_recipients_payload["contact_ids"] == [str(CONTACT_ID)]
    assert (
        client.post(f"/api/v2/labby/campaigns/{CAMPAIGN_ID}/preview-recipients").status_code
        == 200
    )
    assert service.preview_campaign_id == str(CAMPAIGN_ID)
    assert client.post(f"/api/v2/labby/campaigns/{CAMPAIGN_ID}/start").status_code == 200
    assert service.started_campaign_id == str(CAMPAIGN_ID)
    assert (
        client.post(
            f"/api/v2/labby/campaigns/{CAMPAIGN_ID}/dispatch",
            json={"idempotency_key": "dispatch:test"},
        ).status_code
        == 200
    )
    assert service.dispatch_payload["idempotency_key"] == "dispatch:test"
    assert client.post(f"/api/v2/labby/campaigns/{CAMPAIGN_ID}/cancel").status_code == 200
    assert service.cancelled_campaign_id == str(CAMPAIGN_ID)
    assert client.delete(f"/api/v2/labby/campaigns/{CAMPAIGN_ID}").status_code == 200


def test_canonical_sales_campaign_routes_are_available() -> None:
    client, service = make_client()

    assert client.get("/api/v2/labby/sales/campaigns/").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/sales/campaigns/",
            json={"nome": "Promo", "conteudo": "Ola", "contatos_ids": [str(CONTACT_ID)]},
        ).status_code
        == 201
    )
    assert client.get(f"/api/v2/labby/sales/campaigns/{CAMPAIGN_ID}").status_code == 200
    assert (
        client.post(f"/api/v2/labby/sales/campaigns/{CAMPAIGN_ID}/start").status_code == 200
    )
    assert (
        client.post(f"/api/v2/labby/sales/campaigns/{CAMPAIGN_ID}/dispatch", json={}).status_code
        == 200
    )
    assert service.current.tenant_id == TENANT_ID


def test_campaign_update_accepts_legacy_frontend_payload_extras() -> None:
    client, service = make_client()

    response = client.put(
        f"/api/v2/labby/campaigns/{CAMPAIGN_ID}",
        json={
            "nome": "Promo Julho",
            "media_url": "https://example.com/image.png",
            "filtro_tags": ["vip"],
            "filtro_grupo": "Leads",
            "contatos_ids": [str(CONTACT_ID)],
            "status": "queued",
        },
    )

    assert response.status_code == 200
    assert service.updated_payload["patch"] == {"nome": "Promo Julho"}


def test_campaigns_router_requires_sales_module() -> None:
    client, _ = make_client(modules=("social_media",))

    response = client.get("/api/v2/labby/campaigns/")

    assert response.status_code == 403
    assert response.json()["detail"] == "Modulo nao habilitado"
