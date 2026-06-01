from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient

from app.api.v2.labby.social_news import get_social_news_service
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.jobs.job_service import JobRecord
from app.main import create_app


class FakeSocialNewsService:
    def __init__(self) -> None:
        self.current = None
        self.segment_id = None

    def start_run(self, *, current, segment_id, idempotency_key=None, run_type="manual"):
        self.current = current
        self.segment_id = segment_id
        return make_run_row(idempotency_key=idempotency_key or "manual:test"), make_job_record()

    def unsubscribe_by_token(self, *, token, ip=None, user_agent=None):
        return {
            "id": UUID("77777777-7777-7777-7777-777777777777"),
            "status": "unsubscribed",
        }


def make_current() -> CurrentMembership:
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
        membership_id=UUID("33333333-3333-3333-3333-333333333333"),
        email="admin@example.com",
        nome="Admin",
        role="admin",
        modules=("social_media",),
    )


def make_run_row(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("55555555-5555-5555-5555-555555555555"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "membership_id": UUID("33333333-3333-3333-3333-333333333333"),
        "segment_id": UUID("44444444-4444-4444-4444-444444444444"),
        "job_id": UUID("66666666-6666-6666-6666-666666666666"),
        "run_type": "manual",
        "status": "queued",
        "idempotency_key": "manual:test",
        "window_start_at": now,
        "candidates_count": 0,
        "ranked_count": 0,
        "approved_stage1_count": 0,
        "approved_stage2_count": 0,
        "sent_count": 0,
        "failed_count": 0,
        "error_code": None,
        "error_message": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_job_record() -> JobRecord:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    return JobRecord(
        id="66666666-6666-6666-6666-666666666666",
        tenant_id="22222222-2222-2222-2222-222222222222",
        membership_id="33333333-3333-3333-3333-333333333333",
        job_type="social.news.capture",
        queue_name="worker-social-ingestion",
        status="pending",
        priority=10,
        idempotency_key="social.news.capture:manual:test",
        payload={},
        result=None,
        error_code=None,
        error_message=None,
        attempts=0,
        max_attempts=3,
        run_after=now,
        locked_at=None,
        locked_by=None,
        created_at=now,
        updated_at=now,
    )


def make_client(service: FakeSocialNewsService | None = None):
    fake_service = service or FakeSocialNewsService()
    app = create_app()
    app.dependency_overrides[get_social_news_service] = lambda: fake_service
    app.dependency_overrides[get_current_membership] = make_current
    return TestClient(app), fake_service


def test_start_social_news_run_returns_enqueued_job() -> None:
    client, service = make_client()

    response = client.post(
        "/api/v2/labby/social/news/runs",
        json={
            "segment_id": "44444444-4444-4444-4444-444444444444",
            "idempotency_key": "manual:test",
        },
    )

    assert response.status_code == 202
    assert service.segment_id == "44444444-4444-4444-4444-444444444444"
    assert service.current.tenant_id == UUID("22222222-2222-2222-2222-222222222222")
    assert response.json()["job"] == {
        "id": "66666666-6666-6666-6666-666666666666",
        "job_type": "social.news.capture",
        "queue_name": "worker-social-ingestion",
        "status": "pending",
        "idempotency_key": "social.news.capture:manual:test",
    }


def test_unsubscribe_endpoint_is_public() -> None:
    client, _ = make_client()

    response = client.post("/api/v2/labby/social/news/unsubscribe/token")

    assert response.status_code == 200
    assert response.json() == {
        "status": "unsubscribed",
        "subscriber_id": "77777777-7777-7777-7777-777777777777",
    }
