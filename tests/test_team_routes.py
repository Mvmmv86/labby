from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.auth import REFRESH_COOKIE_NAME
from app.api.v2.labby.team import get_team_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.identity.modules import modules_payload
from app.integrations.email import EmailDeliveryResult
from app.main import create_app
from app.schemas.auth import AuthResponse, TenantResponse, UserResponse
from app.schemas.team import LabbyTeamInvite, PublicTeamInvite, TeamInvitesResponse


class FakeTeamService:
    def __init__(self) -> None:
        self.created_payload = None
        self.accept_payload = None

    def list_invites(self, **kwargs):
        assert kwargs["status"] == "pending"
        return TeamInvitesResponse(
            invites=[make_invite()],
            total=1,
            limit=50,
            offset=0,
        )

    def create_invite(self, **kwargs):
        self.created_payload = kwargs
        return make_invite(), EmailDeliveryResult(sent=True)

    def resend_invite(self, **kwargs):
        assert kwargs["invite_id"] == "invite-1"
        return make_invite(resend_count=1), EmailDeliveryResult(sent=False, error="sem chave")

    def revoke_invite(self, **kwargs):
        assert kwargs["invite_id"] == "invite-1"
        return make_invite(status="revoked")

    def public_invite(self, *, token: str):
        assert token == "public-token"
        return PublicTeamInvite(
            id="invite-1",
            tenant={"id": "22222222-2222-2222-2222-222222222222", "nome": "Labby"},
            email="paula@example.com",
            nome="Paula",
            role="agent",
            default_module="social_media",
            expires_at=datetime(2026, 6, 3, tzinfo=UTC),
            modules=modules_payload(("social_media",)),
        )

    def accept_invite(self, **kwargs):
        self.accept_payload = kwargs
        return make_auth_response(), "refresh-accepted"


def make_invite(status: str = "pending", resend_count: int = 0) -> LabbyTeamInvite:
    return LabbyTeamInvite(
        id="invite-1",
        tenant_id="22222222-2222-2222-2222-222222222222",
        email="paula@example.com",
        nome="Paula",
        role="agent",
        default_module="social_media",
        status=status,
        expires_at=datetime(2026, 6, 3, tzinfo=UTC),
        last_sent_at=datetime(2026, 5, 29, tzinfo=UTC),
        resend_count=resend_count,
        invited_by_id="33333333-3333-3333-3333-333333333333",
        invited_by_nome="Marcus",
        accepted_at=None,
        revoked_at=None,
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
        updated_at=datetime(2026, 5, 29, tzinfo=UTC),
        modules=modules_payload(("social_media",)),
    )


def make_auth_response() -> AuthResponse:
    return AuthResponse(
        access_token="accepted-access",
        token_type="bearer",
        user=UserResponse(
            id="11111111-1111-1111-1111-111111111111",
            tenant_id="22222222-2222-2222-2222-222222222222",
            nome="Paula",
            email="paula@example.com",
            avatar_url=None,
            role="agent",
        ),
        tenant=TenantResponse(
            id="22222222-2222-2222-2222-222222222222",
            nome="Labby",
            slug="labby",
            plano="trial",
            ativo=True,
            modules=modules_payload(("social_media",)),
            default_module="social_media",
        ),
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


def make_client(service: FakeTeamService | None = None) -> tuple[TestClient, FakeTeamService]:
    fake_service = service or FakeTeamService()
    app = create_app()
    app.dependency_overrides[get_team_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = make_current_membership
    return TestClient(app), fake_service


def test_list_invites_contract() -> None:
    client, _ = make_client()

    response = client.get("/api/v2/labby/team/invites", params={"status": "pending"})

    assert response.status_code == 200
    assert response.json()["invites"][0]["email"] == "paula@example.com"


def test_create_invite_contract() -> None:
    service = FakeTeamService()
    client, _ = make_client(service)

    response = client.post(
        "/api/v2/labby/team/invites",
        json={
            "nome": "Paula",
            "email": "paula@example.com",
            "role": "agent",
            "module_keys": ["social_media"],
            "default_module": "social_media",
        },
    )

    assert response.status_code == 201
    assert response.json()["email_sent"] is True
    assert service.created_payload["module_keys"] == ["social_media"]


def test_resend_and_revoke_invite_contracts() -> None:
    client, _ = make_client()

    resend = client.post("/api/v2/labby/team/invites/invite-1/resend")
    revoke = client.post("/api/v2/labby/team/invites/invite-1/revoke")

    assert resend.status_code == 200
    assert resend.json()["email_sent"] is False
    assert revoke.status_code == 200
    assert revoke.json()["invite"]["status"] == "revoked"


def test_public_invite_and_accept_contracts() -> None:
    service = FakeTeamService()
    client, _ = make_client(service)

    preview = client.get("/api/v2/labby/team/invites/accept/public-token")
    accepted = client.post(
        "/api/v2/labby/team/invites/accept/public-token",
        json={"senha": "secret123"},
    )

    assert preview.status_code == 200
    assert preview.json()["modules"][0]["key"] == "social_media"
    assert accepted.status_code == 200
    assert accepted.json()["access_token"] == "accepted-access"
    assert "refresh-accepted" in accepted.headers["set-cookie"]
    assert REFRESH_COOKIE_NAME in accepted.headers["set-cookie"]
    assert service.accept_payload == {
        "token": "public-token",
        "senha": "secret123",
        "nome": None,
    }
