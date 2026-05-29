from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.modules import get_module_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.identity.modules import modules_payload
from app.main import create_app
from app.schemas.modules import (
    CurrentModulesResponse,
    LabbyUserModule,
    UpdateUserModulesResponse,
    UserModulesResponse,
    UserModulesStats,
)


class FakeModuleService:
    def __init__(self) -> None:
        self.updated_payload = None

    def current_modules(self, current: CurrentMembership):
        assert current.membership_id == UUID("33333333-3333-3333-3333-333333333333")
        return CurrentModulesResponse(
            modules=modules_payload(("sales", "social_media")),
            default_module="sales",
        )

    def list_users(self, **kwargs):
        assert kwargs["current"].tenant_id == UUID("22222222-2222-2222-2222-222222222222")
        assert kwargs["limit"] == 20
        assert kwargs["offset"] == 10
        assert kwargs["search"] == "paula"
        return UserModulesResponse(
            users=[
                LabbyUserModule(
                    id="11111111-1111-1111-1111-111111111111",
                    nome="Paula",
                    email="paula@example.com",
                    role="agent",
                    ativo=True,
                    default_module="social_media",
                    updated_at=datetime(2026, 5, 29, tzinfo=UTC),
                    modules=modules_payload(("social_media",)),
                )
            ],
            total=1,
            limit=20,
            offset=10,
            stats=UserModulesStats(total=1, sales=0, social_media=1),
        )

    def update_user_modules(self, **kwargs):
        self.updated_payload = kwargs
        return UpdateUserModulesResponse(
            user_id=kwargs["user_id"],
            modules=modules_payload(("sales",)),
            default_module="sales",
            updated_at=datetime(2026, 5, 29, tzinfo=UTC),
        )


def make_current_membership() -> CurrentMembership:
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
        membership_id=UUID("33333333-3333-3333-3333-333333333333"),
        email="marcus@example.com",
        nome="Marcus",
        role="owner",
        modules=("sales", "social_media"),
    )


def make_client(service: FakeModuleService | None = None) -> tuple[TestClient, FakeModuleService]:
    fake_service = service or FakeModuleService()
    app = create_app()
    app.dependency_overrides[get_module_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = make_current_membership
    return TestClient(app), fake_service


def test_current_modules_contract() -> None:
    client, _ = make_client()

    response = client.get("/api/v2/labby/modules/")

    assert response.status_code == 200
    assert response.json()["default_module"] == "sales"
    assert [module["key"] for module in response.json()["modules"]] == ["sales", "social_media"]


def test_list_user_modules_contract() -> None:
    client, _ = make_client()

    response = client.get(
        "/api/v2/labby/modules/users",
        params={"limit": 20, "offset": 10, "search": "paula"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["users"][0]["id"] == "11111111-1111-1111-1111-111111111111"
    assert body["users"][0]["modules"][0]["key"] == "social_media"


def test_update_user_modules_contract() -> None:
    service = FakeModuleService()
    client, _ = make_client(service)

    response = client.patch(
        "/api/v2/labby/modules/users/11111111-1111-1111-1111-111111111111",
        json={
            "module_keys": ["sales"],
            "default_module": "sales",
            "expected_updated_at": "2026-05-29T00:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["modules"][0]["key"] == "sales"
    assert service.updated_payload["user_id"] == "11111111-1111-1111-1111-111111111111"
