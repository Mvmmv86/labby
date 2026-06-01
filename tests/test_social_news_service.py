from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core.dependencies import CurrentMembership
from app.domains.jobs.job_service import JobRecord
from app.domains.social_media.news_service import (
    SOCIAL_AI_QUEUE,
    SOCIAL_INGESTION_QUEUE,
    SOCIAL_NEWS_CAPTURE_JOB,
    SOCIAL_NEWS_REWRITE_JOB,
    SocialNewsService,
)


class FakeResult:
    def __init__(self, *, row=None, rows=None) -> None:
        self.row = row
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.row

    def one(self):
        return self.row

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return self.results.pop(0)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeJobQueue:
    def __init__(self) -> None:
        self.calls = []

    def enqueue_job(self, **kwargs):
        self.calls.append(kwargs)
        return make_job_record(**kwargs)


def make_current(role: str = "admin", modules: tuple[str, ...] = ("social_media",)):
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
        membership_id=UUID("33333333-3333-3333-3333-333333333333"),
        email="admin@example.com",
        nome="Admin",
        role=role,
        modules=modules,
    )


def make_segment_row(**overrides):
    row = {
        "id": UUID("44444444-4444-4444-4444-444444444444"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "slug": "crypto",
        "name": "Crypto",
        "status": "active",
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
        "job_id": None,
        "run_type": "manual",
        "status": "queued",
        "idempotency_key": "manual:crypto",
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


def make_job_record(**kwargs):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    return JobRecord(
        id="66666666-6666-6666-6666-666666666666",
        tenant_id=kwargs["tenant_id"],
        membership_id=kwargs["membership_id"],
        job_type=kwargs["job_type"],
        queue_name=kwargs["queue_name"],
        status="pending",
        priority=kwargs["priority"],
        idempotency_key=kwargs["idempotency_key"],
        payload=kwargs["payload"],
        result=None,
        error_code=None,
        error_message=None,
        attempts=0,
        max_attempts=kwargs["max_attempts"],
        run_after=now,
        locked_at=None,
        locked_by=None,
        created_at=now,
        updated_at=now,
    )


def test_admin_without_social_module_is_blocked() -> None:
    service = SocialNewsService(db=None)

    with pytest.raises(HTTPException) as exc:
        service._assert_social_media_access(make_current(modules=("sales",)))

    assert exc.value.status_code == 403


def test_owner_can_access_even_without_social_module() -> None:
    service = SocialNewsService(db=None)

    service._assert_social_media_access(make_current(role="owner", modules=("sales",)))


def test_start_run_creates_tenant_scoped_capture_job() -> None:
    segment_id = "44444444-4444-4444-4444-444444444444"
    job_id = UUID("66666666-6666-6666-6666-666666666666")
    db = FakeSession(
        [
            FakeResult(row=make_segment_row()),
            FakeResult(row=make_run_row()),
            FakeResult(row=make_run_row(job_id=job_id)),
        ]
    )
    job_queue = FakeJobQueue()
    service = SocialNewsService(db=db, job_queue=job_queue)

    run, job = service.start_run(
        current=make_current(),
        segment_id=segment_id,
        idempotency_key="manual:crypto",
    )

    assert run["job_id"] == job_id
    assert job.job_type == SOCIAL_NEWS_CAPTURE_JOB
    assert job.queue_name == SOCIAL_INGESTION_QUEUE
    assert job_queue.calls[0]["tenant_id"] == "22222222-2222-2222-2222-222222222222"
    assert job_queue.calls[0]["payload"] == {
        "run_id": "55555555-5555-5555-5555-555555555555",
        "segment_id": segment_id,
        "provider": "x",
    }
    assert "ON CONFLICT (tenant_id, run_type, idempotency_key)" in db.calls[1][0]


def test_approve_stage1_moves_item_and_enqueues_rewrite_job() -> None:
    item_id = "77777777-7777-7777-7777-777777777777"
    db = FakeSession(
        [
            FakeResult(row=make_item_row(status="ranked")),
            FakeResult(row=make_item_row(status="approved_stage1")),
            FakeResult(),
            FakeResult(),
        ]
    )
    job_queue = FakeJobQueue()
    service = SocialNewsService(db=db, job_queue=job_queue)

    item, job = service.approve_stage1(current=make_current(), item_id=item_id)

    assert item["status"] == "approved_stage1"
    assert job is not None
    assert job.job_type == SOCIAL_NEWS_REWRITE_JOB
    assert job.queue_name == SOCIAL_AI_QUEUE
    assert job_queue.calls[0]["payload"] == {
        "item_id": item_id,
        "run_id": "55555555-5555-5555-5555-555555555555",
        "segment_id": "44444444-4444-4444-4444-444444444444",
    }
    assert job_queue.calls[0]["commit"] is False
    assert "FOR UPDATE" in db.calls[0][0]
    assert "status = :status" in db.calls[1][0]


def test_approve_stage1_can_skip_rewrite_enqueue_for_frontend_parity() -> None:
    item_id = "77777777-7777-7777-7777-777777777777"
    db = FakeSession(
        [
            FakeResult(row=make_item_row(status="ranked")),
            FakeResult(row=make_item_row(status="approved_stage1")),
            FakeResult(),
        ]
    )
    job_queue = FakeJobQueue()
    service = SocialNewsService(db=db, job_queue=job_queue)

    item, job = service.approve_stage1(
        current=make_current(),
        item_id=item_id,
        rewrite_on_approve=False,
    )

    assert item["status"] == "approved_stage1"
    assert job is None
    assert job_queue.calls == []
    assert db.commits == 1
