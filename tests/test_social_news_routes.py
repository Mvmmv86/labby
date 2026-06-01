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

    def list_segments(self, *, current, status=None, active=None, limit=50, offset=0):
        self.current = current
        return [make_segment_row()]

    def create_segment_from_seed(self, *, current, seed_origem):
        self.current = current
        return make_segment_row(config={"idioma": "pt", "seed_origem": seed_origem})

    def get_segment(self, *, current, segment_id):
        self.current = current
        return make_segment_row(id=UUID(str(segment_id)))

    def update_segment(self, *, current, segment_id, patch):
        self.current = current
        return make_segment_row(id=UUID(str(segment_id)), **patch)

    def delete_segment(self, *, current, segment_id):
        self.current = current

    def list_sources(self, *, current, segment_id):
        self.current = current
        return [make_source_row(segment_id=UUID(str(segment_id)))]

    def add_source(
        self,
        *,
        current,
        segment_id,
        source_type,
        value,
        provider="x",
        min_likes=0,
        min_reposts=0,
        min_replies=0,
        min_impressions=0,
        metadata=None,
    ):
        self.current = current
        return make_source_row(
            segment_id=UUID(str(segment_id)),
            source_type=source_type,
            value=value,
        )

    def delete_source(self, *, current, source_id):
        self.current = current

    def get_curator(self, *, current, segment_id):
        self.current = current
        return make_curator_row(segment_id=UUID(str(segment_id)))

    def upsert_curator(
        self,
        *,
        current,
        segment_id,
        name,
        model="gpt-4o-mini",
        temperature=0.4,
        max_tokens=600,
        system_prompt=None,
        base_knowledge=None,
        active=None,
    ):
        self.current = current
        return make_curator_row(
            segment_id=UUID(str(segment_id)),
            name=name,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
            base_knowledge=base_knowledge,
            status="active" if active is not False else "inactive",
        )

    def start_run(self, *, current, segment_id, idempotency_key=None, run_type="manual"):
        self.current = current
        self.segment_id = segment_id
        return make_run_row(idempotency_key=idempotency_key or "manual:test"), make_job_record()

    def list_runs(
        self,
        *,
        current,
        segment_id=None,
        run_type=None,
        status=None,
        limit=50,
        offset=0,
    ):
        self.current = current
        return [make_run_row(run_type=run_type or "manual", status=status or "queued")]

    def get_run(self, *, current, run_id):
        self.current = current
        return make_run_row(id=UUID(str(run_id)))

    def list_run_items(self, *, current, run_id, status=None, limit=100):
        self.current = current
        return [make_item_row(run_id=UUID(str(run_id)), status=status or "ranked")]

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

    def list_schedules(self, *, current, segment_id=None, active_only=False):
        self.current = current
        return [make_schedule_row(segment_id=UUID(str(segment_id)) if segment_id else None)]

    def recalibrate_schedules(self, *, current, segment_id):
        self.current = current
        return (
            make_run_row(run_type="calibration", status="succeeded"),
            [make_schedule_row(segment_id=UUID(str(segment_id)))],
        )

    def update_schedule(self, *, current, schedule_id, patch):
        self.current = current
        return make_schedule_row(id=UUID(str(schedule_id)), **patch)

    def delete_schedule(self, *, current, schedule_id):
        self.current = current

    def list_subscribers(
        self,
        *,
        current,
        segment_id=None,
        status=None,
        limit=100,
        offset=0,
    ):
        self.current = current
        if segment_id:
            return [make_subscriber_row(segment_id=UUID(str(segment_id)))]
        return [make_subscriber_row()]

    def create_subscriber(
        self,
        *,
        current,
        segment_id,
        email,
        name=None,
        origin="manual",
        consent_source="admin",
        metadata=None,
    ):
        self.current = current
        return make_subscriber_row(
            segment_id=UUID(str(segment_id)),
            email_normalized=email,
            name=name,
            origin=origin,
            metadata_json=metadata or {},
            unsubscribe_token="subscriber.token",
        )

    def update_subscriber(self, *, current, subscriber_id, patch):
        self.current = current
        return make_subscriber_row(id=UUID(str(subscriber_id)), **patch)

    def delete_subscriber(self, *, current, subscriber_id):
        self.current = current

    def unsubscribe_by_token(self, *, token, ip=None, user_agent=None):
        return {
            "id": UUID("77777777-7777-7777-7777-777777777777"),
            "segment_id": UUID("44444444-4444-4444-4444-444444444444"),
            "email_normalized": "user@example.com",
            "status": "unsubscribed",
        }

    def resolve_unsubscribe_token(self, token):
        return {
            "id": UUID("77777777-7777-7777-7777-777777777777"),
            "segment_id": UUID("44444444-4444-4444-4444-444444444444"),
            "email_normalized": "user@example.com",
            "status": "active",
        }


class StatefulCurationService(FakeSocialNewsService):
    def __init__(self) -> None:
        super().__init__()
        self.item_id = UUID("77777777-7777-7777-7777-777777777777")
        self.run_id = UUID("55555555-5555-5555-5555-555555555555")
        self.items = {
            str(self.item_id): make_item_row(
                status="ranked",
                ranking_source="engagement",
                author_metadata={"followers_count": 123, "verified": True},
                media_urls=["https://cdn.example.com/image.png"],
                metrics={"likes": 10, "retweets": 2, "replies": 1},
            )
        }
        self.dispatches = []

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
        return [
            item
            for item in self.items.values()
            if status is None or item["status"] == status
        ][offset : offset + limit]

    def get_item(self, *, current, item_id):
        self.current = current
        return self.items[str(item_id)]

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
        item = self.items[str(item_id)]
        item.update(
            status="approved_stage1",
            approved_stage1_by_membership_id=current.membership_id,
            approved_stage1_at=datetime(2026, 6, 1, 12, 5, tzinfo=UTC),
        )
        if rewrite_on_approve:
            item.update(
                status="rewritten",
                rewritten_content="Texto final do digest.",
                rewritten_model="fallback-editorial",
                rewritten_at=datetime(2026, 6, 1, 12, 6, tzinfo=UTC),
            )
        return item, make_job_record(job_type="social.news.rewrite", queue_name="worker-ai")

    def reject_stage1(self, *, current, item_id, rejection_reason=None):
        self.current = current
        item = self.items[str(item_id)]
        item.update(status="rejected_stage1", rejection_reason=rejection_reason)
        return item

    def approve_stage2(self, *, current, item_id):
        self.current = current
        item = self.items[str(item_id)]
        item.update(
            status="approved_stage2",
            approved_stage2_by_membership_id=current.membership_id,
            approved_stage2_at=datetime(2026, 6, 1, 12, 7, tzinfo=UTC),
        )
        return item

    def enqueue_dispatch(self, *, current, run_id, idempotency_key=None):
        self.current = current
        self.dispatch_run_id = run_id
        self.dispatches.append(make_dispatch_row(run_id=UUID(str(run_id))))
        return make_job_record(
            job_type="social.news.dispatch",
            queue_name="worker-email",
            idempotency_key="social.news.dispatch:run:test",
        )

    def dispatch_preview(self, *, current, run_id):
        self.current = current
        return {
            "run_id": UUID(str(run_id)),
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "subscribers": 1,
            "items": 1,
        }

    def list_dispatches(self, *, current, run_id=None, limit=100):
        self.current = current
        return self.dispatches[:limit]


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


def make_segment_row(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("44444444-4444-4444-4444-444444444444"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "slug": "crypto",
        "name": "Criptomoeda",
        "description": "Noticias crypto",
        "base_knowledge": None,
        "disclaimer": None,
        "min_engagement_score": 0,
        "status": "active",
        "config": {"idioma": "pt", "tipos_evento": [], "vocabulario": []},
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_source_row(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "segment_id": UUID("44444444-4444-4444-4444-444444444444"),
        "provider": "x",
        "source_type": "x_keyword",
        "value": "bitcoin",
        "min_likes": 0,
        "min_reposts": 0,
        "min_replies": 0,
        "min_impressions": 0,
        "status": "active",
        "metadata_json": {"origem": "user"},
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_curator_row(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "segment_id": UUID("44444444-4444-4444-4444-444444444444"),
        "name": "Editor",
        "model": "gpt-4o-mini",
        "temperature": 0.4,
        "max_tokens": 600,
        "system_prompt": None,
        "base_knowledge": None,
        "status": "active",
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_schedule_row(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("cccccccc-cccc-cccc-cccc-cccccccccccc"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "segment_id": UUID("44444444-4444-4444-4444-444444444444"),
        "name": "Exploratorio diario 09:00",
        "timezone": "America/Sao_Paulo",
        "day_of_week": None,
        "window_start_hour": 9,
        "window_end_hour": 13,
        "scheduled_hour": 9,
        "scheduled_minute": 0,
        "confidence_score": 45,
        "samples_count": 0,
        "average_score": None,
        "discovered_by": "exploratorio_fixo",
        "origin_run_id": None,
        "status": "active",
        "last_run_at": None,
        "next_run_at": now,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def make_subscriber_row(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("dddddddd-dddd-dddd-dddd-dddddddddddd"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "segment_id": UUID("44444444-4444-4444-4444-444444444444"),
        "email_normalized": "user@example.com",
        "name": "User",
        "status": "active",
        "origin": "manual",
        "consent_status": "granted",
        "consent_source": "admin",
        "consent_given_at": now,
        "unsubscribed_at": None,
        "metadata_json": {},
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


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
        "author_metadata": {},
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
        "email": "user@example.com",
        "segment_id": "44444444-4444-4444-4444-444444444444",
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
    assert body["status"] == "aprovado_stage1"
    assert body["autor_handle"] == "labby"
    assert body["conteudo_original"] == "Labby captured an important update with enough content."
    assert "original_content" not in body
    assert service.stage1_rewrite_on_approve is False


def test_frontend_curation_stage_lists_use_expected_status_filters() -> None:
    client, service = make_client()

    response = client.get("/api/v2/labby/social/news/curation/stage1")

    assert response.status_code == 200
    assert service.list_status == "ranked"
    body = response.json()
    assert body["items"][0]["status"] == "ranqueado"
    assert body["items"][0]["ranking_origem"] == "top_engagement"


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
    assert "job" not in body


def test_frontend_dispatches_route_returns_dispatch_rows() -> None:
    client, _ = make_client()

    response = client.get("/api/v2/labby/social/news/curation/dispatches")

    assert response.status_code == 200
    dispatch = response.json()["dispatches"][0]
    assert dispatch["status"] == "sent"
    assert dispatch["email"] == "user@example.com"
    assert dispatch["resend_id"] == "msg_1"


def test_frontend_dispatch_config_route_is_available() -> None:
    client, service = make_client()

    response = client.get("/api/v2/labby/social/news/curation/dispatch-config")

    assert response.status_code == 200
    assert service.current.tenant_id == UUID("22222222-2222-2222-2222-222222222222")
    assert "email_enabled" in response.json()


def test_frontend_curation_e2e_contract_from_stage1_to_dispatch() -> None:
    service = StatefulCurationService()
    client, _ = make_client(service)
    item_id = "77777777-7777-7777-7777-777777777777"
    run_id = "55555555-5555-5555-5555-555555555555"

    stage1 = client.get("/api/v2/labby/social/news/curation/stage1")
    assert stage1.status_code == 200
    stage1_item = stage1.json()["items"][0]
    assert stage1_item["status"] == "ranqueado"
    assert stage1_item["autor_verified"] is True
    assert stage1_item["autor_followers_count"] == 123
    assert stage1_item["media_urls"] == ["https://cdn.example.com/image.png"]

    approve_stage1 = client.post(
        f"/api/v2/labby/social/news/curation/items/{item_id}/stage1",
        json={"action": "approve", "rewrite_on_approve": True},
    )
    assert approve_stage1.status_code == 200
    assert approve_stage1.json()["status"] == "reescrito"
    assert approve_stage1.json()["conteudo_reescrito"] == "Texto final do digest."

    stage2 = client.get("/api/v2/labby/social/news/curation/stage2")
    assert stage2.status_code == 200
    assert stage2.json()["items"][0]["status"] == "reescrito"

    approve_stage2 = client.post(
        f"/api/v2/labby/social/news/curation/items/{item_id}/stage2",
        json={"action": "approve"},
    )
    assert approve_stage2.status_code == 200
    assert approve_stage2.json()["status"] == "aprovado_stage2"

    ready = client.get("/api/v2/labby/social/news/curation/ready")
    assert ready.status_code == 200
    assert ready.json()["items"][0]["status"] == "aprovado_stage2"

    dispatch = client.post(f"/api/v2/labby/social/news/curation/runs/{run_id}/dispatch")
    assert dispatch.status_code == 200
    assert dispatch.json() == {
        "run_id": run_id,
        "sent": 0,
        "failed": 0,
        "skipped": 0,
        "subscribers": 1,
        "items": 1,
    }

    dispatches = client.get("/api/v2/labby/social/news/curation/dispatches")
    assert dispatches.status_code == 200
    assert dispatches.json()["dispatches"][0]["email"] == "user@example.com"


def test_frontend_social_parity_routes_are_available() -> None:
    client, _ = make_client()
    segment_id = "44444444-4444-4444-4444-444444444444"
    source_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    run_id = "55555555-5555-5555-5555-555555555555"
    schedule_id = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    subscriber_id = "dddddddd-dddd-dddd-dddd-dddddddddddd"

    assert client.get("/api/v2/labby/social/news/segments").status_code == 200
    assert client.get(f"/api/v2/labby/social/news/segments/{segment_id}").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/social/news/segments/from-seed",
            json={"seed_origem": "crypto_v1"},
        ).status_code
        == 201
    )
    assert (
        client.patch(
            f"/api/v2/labby/social/news/segments/{segment_id}",
            json={"nome": "Crypto BR", "ativo": True},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v2/labby/social/news/segments/{segment_id}/sources").status_code == 200
    assert (
        client.post(
            f"/api/v2/labby/social/news/segments/{segment_id}/sources",
            json={"source_type": "x_keyword", "valor": "bitcoin"},
        ).status_code
        == 201
    )
    assert client.delete(f"/api/v2/labby/social/news/sources/{source_id}").status_code == 204
    assert client.get(f"/api/v2/labby/social/news/segments/{segment_id}/curator").status_code == 200
    assert (
        client.put(
            f"/api/v2/labby/social/news/segments/{segment_id}/curator",
            json={"nome": "Editor", "modelo": "gpt-4o-mini"},
        ).status_code
        == 200
    )

    manual_run = client.post(
        "/api/v2/labby/social/news/runs/manual",
        json={"segment_id": segment_id},
    )
    assert manual_run.status_code == 202
    assert manual_run.json()["status"] == "capturando"
    assert client.get("/api/v2/labby/social/news/runs").status_code == 200
    assert client.get(f"/api/v2/labby/social/news/runs/{run_id}").status_code == 200
    assert client.get(f"/api/v2/labby/social/news/runs/{run_id}/items").status_code == 200

    schedules = client.get(f"/api/v2/labby/social/news/segments/{segment_id}/schedules")
    assert schedules.status_code == 200
    assert (
        client.post(
            f"/api/v2/labby/social/news/segments/{segment_id}/schedules/recalibrate",
            json={},
        ).status_code
        == 202
    )
    assert (
        client.patch(
            f"/api/v2/labby/social/news/schedules/{schedule_id}",
            json={"scheduled_hour": 10},
        ).status_code
        == 200
    )
    assert client.delete(f"/api/v2/labby/social/news/schedules/{schedule_id}").status_code == 204

    assert client.get("/api/v2/labby/social/news/subscribers").status_code == 200
    assert (
        client.post(
            "/api/v2/labby/social/news/subscribers",
            json={"segment_id": segment_id, "email": "user@example.com", "nome": "User"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v2/labby/social/news/subscribers/import-csv",
            json={"segment_id": segment_id, "csv_text": "email,nome\nnew@example.com,New"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v2/labby/social/news/subscribers/{subscriber_id}",
            json={"status": "unsubscribed"},
        ).status_code
        == 200
    )
    delete_subscriber = client.delete(f"/api/v2/labby/social/news/subscribers/{subscriber_id}")
    assert delete_subscriber.status_code == 204
    assert client.get("/api/v2/labby/social/news/unsubscribe/token").status_code == 200
