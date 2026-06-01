from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.sales_contacts import get_sales_contact_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.main import create_app


class FakeSalesContactService:
    def __init__(self) -> None:
        self.current = None
        self.created_payload = None
        self.updated_payload = None
        self.batch_payload = None

    def list_contacts(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "contacts": [make_contact_list_item()],
            "total": 1,
            "page": kwargs["page"],
            "per_page": kwargs["per_page"],
            "pages": 1,
        }

    def get_contact(self, **kwargs):
        self.current = kwargs["current"]
        return make_contact_detail()

    def create_contact(self, **kwargs):
        self.current = kwargs["current"]
        self.created_payload = kwargs
        return make_contact_mutation(message="Contato criado com sucesso")

    def update_contact(self, **kwargs):
        self.current = kwargs["current"]
        self.updated_payload = kwargs
        return make_contact_mutation(message="Contato atualizado")

    def delete_contact(self, **kwargs):
        self.current = kwargs["current"]
        return {
            "id": UUID("44444444-4444-4444-4444-444444444444"),
            "message": "Contato removido",
        }

    def batch_import_contacts(self, **kwargs):
        self.current = kwargs["current"]
        self.batch_payload = kwargs
        return {
            "total_enviados": 2,
            "importados": 1,
            "duplicados": 1,
            "erros": 0,
            "sem_telefone": 0,
            "detalhes_erros": [],
        }


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


def make_contact_list_item(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("44444444-4444-4444-4444-444444444444"),
        "nome": "Paula",
        "telefone": "5511999990000",
        "email": "paula@example.com",
        "tags": ["vip"],
        "grupo": "Leads",
        "total_conversas": 0,
        "canais_vinculados": [],
        "ultima_interacao": None,
        "created_at": now,
    }
    row.update(overrides)
    return row


def make_contact_detail(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = make_contact_list_item()
    row.update(
        {
            "notas": "Contato quente",
            "campos_custom": {"empresa": "ACME"},
            "total_mensagens_enviadas": 0,
            "total_mensagens_recebidas": 0,
            "optout": False,
            "status": "active",
            "updated_at": now,
            "canais": [],
            "conversas_recentes": [],
        }
    )
    row.update(overrides)
    return row


def make_contact_mutation(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("44444444-4444-4444-4444-444444444444"),
        "nome": "Paula",
        "telefone": "5511999990000",
        "email": "paula@example.com",
        "grupo": "Leads",
        "tags": ["vip"],
        "notas": "Contato quente",
        "campos_custom": {"empresa": "ACME"},
        "created_at": now,
        "updated_at": now,
        "message": "Contato atualizado",
    }
    row.update(overrides)
    return row


def make_client(
    service: FakeSalesContactService | None = None,
    *,
    modules: tuple[str, ...] = ("sales",),
) -> tuple[TestClient, FakeSalesContactService]:
    fake_service = service or FakeSalesContactService()
    app = create_app()
    app.dependency_overrides[get_sales_contact_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = lambda: make_current(modules=modules)
    return TestClient(app), fake_service


def test_flat_contacts_routes_are_available() -> None:
    client, service = make_client()
    contact_id = "44444444-4444-4444-4444-444444444444"

    assert client.get("/api/v2/labby/contacts/").status_code == 200
    assert client.get(f"/api/v2/labby/contacts/{contact_id}").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/contacts/",
            json={
                "nome": "Paula",
                "telefone": "(11) 99999-0000",
                "email": "paula@example.com",
                "grupo": "Leads",
                "tags": ["vip"],
            },
        ).status_code
        == 201
    )
    assert service.created_payload["nome"] == "Paula"
    assert (
        client.put(
            f"/api/v2/labby/contacts/{contact_id}",
            json={"nome": "Paula Silva", "tags": ["lead"]},
        ).status_code
        == 200
    )
    assert service.updated_payload["patch"] == {"nome": "Paula Silva", "tags": ["lead"]}
    assert client.delete(f"/api/v2/labby/contacts/{contact_id}").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/contacts/batch",
            json={
                "contacts": [{"nome": "Paula", "telefone": "(11) 99999-0000"}],
                "on_duplicate": "skip",
            },
        ).status_code
        == 200
    )


def test_canonical_sales_contacts_routes_are_available() -> None:
    client, service = make_client()
    contact_id = "44444444-4444-4444-4444-444444444444"

    assert client.get("/api/v2/labby/sales/contacts/").status_code == 200
    assert client.get(f"/api/v2/labby/sales/contacts/{contact_id}").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/sales/contacts/",
            json={"nome": "Paula", "telefone": "(11) 99999-0000"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v2/labby/sales/contacts/batch",
            json={"contacts": [{"nome": "Paula", "telefone": "(11) 99999-0000"}]},
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v2/labby/sales/contacts/{contact_id}").status_code == 200
    assert service.current.tenant_id == UUID("22222222-2222-2222-2222-222222222222")


def test_contacts_router_requires_sales_module() -> None:
    client, _ = make_client(modules=("social_media",))

    response = client.get("/api/v2/labby/contacts/")

    assert response.status_code == 403
    assert response.json()["detail"] == "Modulo nao habilitado"
