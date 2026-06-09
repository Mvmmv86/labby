from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.social_onboarding import get_social_onboarding_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.jobs.job_service import JobRecord
from app.main import create_app

TENANT_ID = UUID("22222222-2222-2222-2222-222222222222")
MEMBERSHIP_ID = UUID("33333333-3333-3333-3333-333333333333")
SESSION_ID = UUID("44444444-4444-4444-4444-444444444444")
REFERENCE_ID = UUID("55555555-5555-5555-5555-555555555555")
JOB_ID = UUID("66666666-6666-6666-6666-666666666666")


class FakeSocialOnboardingService:
    def __init__(self) -> None:
        self.current = None
        self.created_objective = None
        self.connected_payload = None
        self.reference_payload = None

    def get_current(self, *, current):
        self.current = current
        return make_session_row()

    def create_session(self, *, current, objective):
        self.current = current
        self.created_objective = objective
        return make_session_row(objective=objective)

    def get_session(self, *, current, session_id):
        self.current = current
        return make_session_row(id=UUID(str(session_id)))

    def update_session(self, *, current, session_id, patch):
        self.current = current
        return make_session_row(id=UUID(str(session_id)), **patch)

    def connect_fake_account(
        self,
        *,
        current,
        session_id,
        provider,
        handle,
        display_name,
        profile_url,
        followers_count,
        posts_count,
        average_engagement_rate,
    ):
        self.current = current
        self.connected_payload = {
            "session_id": session_id,
            "provider": provider,
            "handle": handle,
            "display_name": display_name,
            "profile_url": profile_url,
            "followers_count": followers_count,
            "posts_count": posts_count,
            "average_engagement_rate": average_engagement_rate,
        }
        return (
            make_session_row(
                id=UUID(str(session_id)),
                status="analyzing",
                primary_provider=provider,
                connection_mode="simulated",
                connected_account_handle=handle.strip().lstrip("@").lower(),
            ),
            make_job_record(),
        )

    def create_phyllo_connect_token(self, *, current, session_id):
        self.current = current
        return {
            "user_id": "phyllo-user",
            "sdk_token": "sdk-token",
            "environment": "staging",
            "client_display_name": "Labby",
            "work_platform_id": "instagram-platform",
            "products": ["IDENTITY", "ENGAGEMENT"],
        }

    def complete_phyllo_connection(
        self,
        *,
        current,
        session_id,
        phyllo_user_id,
        account_id,
        work_platform_id,
    ):
        self.current = current
        self.connected_payload = {
            "session_id": session_id,
            "phyllo_user_id": phyllo_user_id,
            "account_id": account_id,
            "work_platform_id": work_platform_id,
        }
        return (
            make_session_row(
                id=UUID(str(session_id)),
                status="analyzing",
                primary_provider="instagram",
                connection_mode="oauth",
                connected_account_handle="marca",
            ),
            make_job_record(),
        )

    def add_reference(self, *, current, session_id, provider, handle, label, profile_url):
        self.current = current
        self.reference_payload = {
            "session_id": session_id,
            "provider": provider,
            "handle": handle,
            "label": label,
            "profile_url": profile_url,
        }
        return make_reference_row(provider=provider, handle=handle.strip().lstrip("@").lower())

    def enqueue_diagnostic(self, *, current, session_id):
        self.current = current
        return make_session_row(id=UUID(str(session_id)), status="analyzing"), make_job_record()


def make_current(modules: tuple[str, ...] = ("social_media",)) -> CurrentMembership:
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=TENANT_ID,
        membership_id=MEMBERSHIP_ID,
        email="admin@example.com",
        nome="Admin",
        role="admin",
        modules=modules,
    )


def make_reference_row(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": REFERENCE_ID,
        "provider": "instagram",
        "handle": "referencia",
        "label": "Referencia",
        "profile_url": "https://instagram.com/referencia",
        "status": "active",
        "created_at": now,
    }
    row.update(overrides)
    return row


def make_session_row(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": SESSION_ID,
        "tenant_id": TENANT_ID,
        "objective": "grow_audience",
        "status": "draft",
        "primary_provider": None,
        "connection_mode": "none",
        "connected_account_handle": None,
        "connected_account_name": None,
        "profile_url": None,
        "progress_steps": [{"key": "objective", "label": "Objetivo", "status": "done"}],
        "profile_snapshot": {},
        "analysis_report": None,
        "analysis_version": 0,
        "references": [make_reference_row()],
        "error_code": None,
        "error_message": None,
        "analysis_started_at": None,
        "analysis_completed_at": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_job_record(**overrides):
    now = datetime(2026, 6, 8, tzinfo=UTC)
    row = {
        "id": str(JOB_ID),
        "tenant_id": str(TENANT_ID),
        "membership_id": str(MEMBERSHIP_ID),
        "job_type": "social.onboarding.diagnose",
        "queue_name": "worker-social-analysis",
        "status": "pending",
        "priority": 0,
        "idempotency_key": "social.onboarding.diagnose:session:v1",
        "payload": {"session_id": str(SESSION_ID)},
        "result": None,
        "error_code": None,
        "error_message": None,
        "attempts": 0,
        "max_attempts": 3,
        "run_after": now,
        "locked_at": None,
        "locked_by": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return JobRecord(**row)


def make_client(
    service: FakeSocialOnboardingService | None = None,
    *,
    modules: tuple[str, ...] = ("social_media",),
) -> tuple[TestClient, FakeSocialOnboardingService]:
    fake_service = service or FakeSocialOnboardingService()
    app = create_app()
    app.dependency_overrides[get_social_onboarding_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = lambda: make_current(modules)
    return TestClient(app), fake_service


def test_create_social_onboarding_session_requires_social_module() -> None:
    client, _ = make_client(modules=("sales",))

    response = client.post(
        "/api/v2/labby/social/onboarding/sessions",
        json={"objective": "grow_audience"},
    )

    assert response.status_code == 403


def test_social_onboarding_current_contract() -> None:
    client, service = make_client()

    response = client.get("/api/v2/labby/social/onboarding/current")

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["id"] == str(SESSION_ID)
    assert body["session"]["references"][0]["handle"] == "referencia"
    assert service.current.tenant_id == TENANT_ID


def test_create_social_onboarding_session_contract() -> None:
    client, service = make_client()

    response = client.post(
        "/api/v2/labby/social/onboarding/sessions",
        json={"objective": "benchmarking"},
    )

    assert response.status_code == 201
    assert response.json()["objective"] == "benchmarking"
    assert service.created_objective == "benchmarking"


def test_connect_fake_account_enqueues_diagnostic_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/fake-connect",
        json={
            "provider": "instagram",
            "handle": "@MinhaMarca",
            "display_name": "Minha Marca",
            "followers_count": 1200,
            "posts_count": 88,
            "average_engagement_rate": 2.4,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["status"] == "analyzing"
    assert body["session"]["connected_account_handle"] == "minhamarca"
    assert body["job"]["job_type"] == "social.onboarding.diagnose"
    assert service.connected_payload["handle"] == "@MinhaMarca"


def test_create_phyllo_connect_token_contract() -> None:
    client, _ = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/phyllo/connect-token",
    )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "user_id": "phyllo-user",
        "sdk_token": "sdk-token",
        "environment": "staging",
        "client_display_name": "Labby",
        "work_platform_id": "instagram-platform",
        "products": ["IDENTITY", "ENGAGEMENT"],
    }


def test_complete_phyllo_connection_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/phyllo/complete",
        json={
            "user_id": "phyllo-user",
            "account_id": "phyllo-account",
            "work_platform_id": "instagram-platform",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["connection_mode"] == "oauth"
    assert body["session"]["connected_account_handle"] == "marca"
    assert body["job"]["job_type"] == "social.onboarding.diagnose"
    assert service.connected_payload["account_id"] == "phyllo-account"


def test_add_reference_contract() -> None:
    client, service = make_client()

    response = client.post(
        f"/api/v2/labby/social/onboarding/sessions/{SESSION_ID}/references",
        json={
            "provider": "x",
            "handle": "@referencia_crypto",
            "label": "Referencia crypto",
        },
    )

    assert response.status_code == 201
    assert response.json()["handle"] == "referencia_crypto"
    assert service.reference_payload["provider"] == "x"
