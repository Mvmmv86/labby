from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.auth import REFRESH_COOKIE_NAME, get_auth_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.identity.modules import modules_payload
from app.main import create_app
from app.schemas.auth import (
    AuthResponse,
    MembershipResponse,
    MeResponse,
    TenantResponse,
    UserResponse,
)


class FakeAuthService:
    def __init__(self) -> None:
        self.logout_token: str | None = None
        self.reset_payload: tuple[str, str] | None = None
        self.forgot_email: str | None = None

    def register(self, **kwargs):
        return make_auth_response(access_token="registered"), "refresh-register"

    def login(self, **kwargs):
        return make_auth_response(access_token="logged-in"), "refresh-login"

    def refresh(self, refresh_token: str):
        assert refresh_token == "old-refresh"
        return make_auth_response(access_token="refreshed"), "new-refresh"

    def logout(self, refresh_token: str | None) -> None:
        self.logout_token = refresh_token

    def me(self, membership_id: str):
        assert membership_id == "33333333-3333-3333-3333-333333333333"
        return MeResponse(
            user=make_user_response(),
            tenant=make_tenant_response(),
            memberships=[
                MembershipResponse(
                    id="33333333-3333-3333-3333-333333333333",
                    tenant_id="22222222-2222-2222-2222-222222222222",
                    tenant_nome="Labby",
                    tenant_slug="labby",
                    role="owner",
                    modules=modules_payload(("sales", "social_media")),
                    default_module="sales",
                )
            ],
        )

    def switch_tenant(self, *, user_id: str, membership_id: str):
        assert user_id == "11111111-1111-1111-1111-111111111111"
        assert membership_id == "44444444-4444-4444-4444-444444444444"
        return make_auth_response(access_token="switched"), "refresh-switch"

    def forgot_password(self, *, email: str):
        self.forgot_email = email
        return "reset-token"

    def reset_password(self, *, token: str, senha: str) -> None:
        self.reset_payload = (token, senha)


def make_user_response() -> UserResponse:
    return UserResponse(
        id="11111111-1111-1111-1111-111111111111",
        tenant_id="22222222-2222-2222-2222-222222222222",
        nome="Marcus",
        email="marcus@example.com",
        avatar_url=None,
        role="owner",
    )


def make_tenant_response() -> TenantResponse:
    return TenantResponse(
        id="22222222-2222-2222-2222-222222222222",
        nome="Labby",
        slug="labby",
        plano="trial",
        ativo=True,
        modules=modules_payload(("sales", "social_media")),
        default_module="sales",
    )


def make_auth_response(access_token: str) -> AuthResponse:
    return AuthResponse(
        access_token=access_token,
        token_type="bearer",
        user=make_user_response(),
        tenant=make_tenant_response(),
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


def make_client(service: FakeAuthService | None = None) -> tuple[TestClient, FakeAuthService]:
    fake_service = service or FakeAuthService()
    app = create_app()
    app.dependency_overrides[get_auth_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = make_current_membership
    return TestClient(app), fake_service


def test_login_sets_http_only_refresh_cookie() -> None:
    client, _ = make_client()

    response = client.post(
        "/api/v2/labby/auth/login",
        json={"email": "marcus@example.com", "senha": "secret123"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "logged-in"
    set_cookie = response.headers["set-cookie"]
    assert REFRESH_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie


def test_refresh_rotates_refresh_cookie_from_body() -> None:
    client, _ = make_client()

    response = client.post(
        "/api/v2/labby/auth/refresh",
        json={"refresh_token": "old-refresh"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "refreshed"
    assert "new-refresh" in response.headers["set-cookie"]


def test_logout_revokes_refresh_and_clears_cookie() -> None:
    service = FakeAuthService()
    client, _ = make_client(service)

    response = client.post(
        "/api/v2/labby/auth/logout",
        json={"refresh_token": "old-refresh"},
    )

    assert response.status_code == 204
    assert service.logout_token == "old-refresh"
    assert REFRESH_COOKIE_NAME in response.headers["set-cookie"]


def test_me_returns_active_membership_context() -> None:
    client, _ = make_client()

    response = client.get("/api/v2/labby/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "marcus@example.com"
    assert body["memberships"][0]["default_module"] == "sales"


def test_switch_tenant_sets_new_refresh_cookie() -> None:
    client, _ = make_client()

    response = client.post(
        "/api/v2/labby/auth/switch-tenant",
        json={"membership_id": "44444444-4444-4444-4444-444444444444"},
    )

    assert response.status_code == 200
    assert response.json()["access_token"] == "switched"
    assert "refresh-switch" in response.headers["set-cookie"]


def test_forgot_and_reset_password_contracts() -> None:
    service = FakeAuthService()
    client, _ = make_client(service)

    forgot = client.post(
        "/api/v2/labby/auth/forgot-password",
        json={"email": "marcus@example.com"},
    )
    reset = client.post(
        "/api/v2/labby/auth/reset-password",
        json={"token": "reset-token", "senha": "new-secret"},
    )

    assert forgot.status_code == 204
    assert reset.status_code == 204
    assert service.forgot_email == "marcus@example.com"
    assert service.reset_payload == ("reset-token", "new-secret")
