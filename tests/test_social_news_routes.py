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
        self.list_status = None
        self.stage1_rewrite_on_approve = None
        self.dispatch_run_id = None

    def _assert_social_media_access(self, current):
        self.current = current

    def start_run(self, *, current, segment_id, idempotency_key=None, run_type="manual"):
        self.current = current
        self.segment_id = segment_id
        return make_run_row(idempotency_key=idempotency_key or "manual:test"), make_job_record()

    def list_items(
        self,
        *,
        current,
        segment_id=None,
        run_id=None,
        status=None,
        limit=100,
        offset=0,
    ):
        self.current = current
        self.list_status = status
        return [make_item_row(status=status or "ranked")]

    def get_item(self, *, current, item_id):
        self.current = current
        return make_item_row(status="approved_stage1")

    def approve_stage1(
        self,
        *,
        current,
        item_id,
        idempotency_key=None,
        rewrite_on_approve=True,
    ):
        self.current = current
        self.stage1_rewrite_on_approve = rewrite_on_approve
        return make_item_row(status="approved_stage1"), make_job_record(
            job_type="social.news.rewrite",
            queue_name="worker-ai",
            idempotency_key="social.news.rewrite:item:test",
        )

    def reject_stage1(self, *, current, item_id, rejection_reason=None):
        self.current = current
        return make_item_row(status="rejected_stage1", rejection_reason=rejection_reason)

    def approve_stage2(self, *, current, item_id):
        self.current = current
        return make_item_row(status="approved_stage2")

    def reject_stage2(self, *, current, item_id, rejection_reason=None):
        self.current = current
        return make_item_row(status="rejected_stage2", rejection_reason=rejection_reason)

    def enqueue_rewrite(self, *, current, item_id, idempotency_key=None):
        self.current = current
        return make_job_record(
            job_type="social.news.rewrite",
            queue_name="worker-ai",
            idempotency_key=idempotency_key or "social.news.rewrite:item:test",
        )

    def enqueue_dispatch(self, *, current, run_id, idempotency_key=None):
        self.current = current
        self.dispatch_run_id = run_id
        return make_job_record(
            job_type="social.news.dispatch",
            queue_name="worker-email",
            idempotency_key=idempotency_key or "social.news.dispatch:run:test",
        )

    def dispatch_preview(self, *, current, run_id):
        self.current = current
        return {
            "run_id": UUID(run_id),
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "subscribers": 2,
            "items": 3,
        }

    def list_dispatches(self, *, current, run_id=None, limit=100):
        self.current = current
        return [make_dispatch_row(run_id=UUID(run_id) if run_id else None)]

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


def make_item_row(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("77777777-7777-7777-7777-777777777777"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "run_id": UUID("55555555-5555-5555-5555-555555555555"),
        "segment_id": UUID("44444444-4444-4444-4444-444444444444"),
        "source_id": None,
        "provider": "x",
        "external_id": "x-1",
        "external_url": "https://x.com/labby/status/1",
        "published_at": now,
        "author_handle": "labby",
        "author_name": "Labby",
        "original_content": "Labby captured an important update with enough content.",
        "rewritten_content": None,
        "rewritten_model": None,
        "rewritten_at": None,
        "media_urls": [],
        "metrics": {},
        "ranking_score": 42,
        "ranking_reason": "score alto",
        "ranking_source": "engagement",
        "type_match": None,
        "status": "ranked",
        "approved_stage1_by_membership_id": None,
        "approved_stage1_at": None,
        "approved_stage2_by_membership_id": None,
        "approved_stage2_at": None,
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_dispatch_row(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("88888888-8888-8888-8888-888888888888"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "run_id": UUID("55555555-5555-5555-5555-555555555555"),
        "subscriber_id": UUID("99999999-9999-9999-9999-999999999999"),
        "email_normalized": "user@example.com",
        "subject": "Digest",
        "status": "sent",
        "idempotency_key": "dispatch:1",
        "provider": "resend",
        "provider_message_id": "msg_1",
        "error_message": None,
        "sent_at": now,
        "created_at": now,
        "updated_at": now,
    }
    row.update({key: value for key, value in overrides.items() if value is not None})
    return row


def make_job_record(
    *,
    job_type: str = "social.news.capture",
    queue_name: str = "worker-social-ingestion",
    idempotency_key: str = "social.news.capture:manual:test",
) -> JobRecord:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    return JobRecord(
        id="66666666-6666-6666-6666-666666666666",
        tenant_id="22222222-2222-2222-2222-222222222222",
        membership_id="33333333-3333-3333-3333-333333333333",
        job_type=job_type,
        queue_name=queue_name,
        status="pending",
        priority=10,
        idempotency_key=idempotency_key,
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


def test_approve_stage1_returns_item_and_rewrite_job() -> None:
    client, _ = make_client()

    response = client.post(
        "/api/v2/labby/social/news/items/77777777-7777-7777-7777-777777777777/approve-stage1",
        json={},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["item"]["status"] == "approved_stage1"
    assert body["job"]["job_type"] == "social.news.rewrite"
    assert body["job"]["queue_name"] == "worker-ai"


def test_frontend_stage1_route_returns_item_directly() -> None:
    client, service = make_client()

    response = client.post(
        "/api/v2/labby/social/news/curation/items/"
        "77777777-7777-7777-7777-777777777777/stage1",
        json={"action": "approve", "rewrite_on_approve": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved_stage1"
    assert service.stage1_rewrite_on_approve is False


def test_frontend_curation_stage_lists_use_expected_status_filters() -> None:
    client, service = make_client()

    response = client.get("/api/v2/labby/social/news/curation/stage1")

    assert response.status_code == 200
    assert service.list_status == "ranked"
    assert response.json()["items"][0]["status"] == "ranked"


def test_frontend_dispatch_route_returns_summary_and_job() -> None:
    client, service = make_client()
    run_id = "55555555-5555-5555-5555-555555555555"

    response = client.post(f"/api/v2/labby/social/news/curation/runs/{run_id}/dispatch")

    assert response.status_code == 200
    body = response.json()
    assert service.dispatch_run_id == run_id
    assert body["run_id"] == run_id
    assert body["subscribers"] == 2
    assert body["items"] == 3
    assert body["job"]["job_type"] == "social.news.dispatch"


def test_frontend_dispatches_route_returns_dispatch_rows() -> None:
    client, _ = make_client()

    response = client.get("/api/v2/labby/social/news/curation/dispatches")

    assert response.status_code == 200
    assert response.json()["dispatches"][0]["status"] == "sent"


def test_frontend_dispatch_config_route_is_available() -> None:
    client, service = make_client()

    response = client.get("/api/v2/labby/social/news/curation/dispatch-config")

    assert response.status_code == 200
    assert service.current.tenant_id == UUID("22222222-2222-2222-2222-222222222222")
    assert "email_enabled" in response.json()
