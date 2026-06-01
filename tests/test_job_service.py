from datetime import UTC, datetime

from app.domains.jobs.job_service import JobQueueService, retry_delay_seconds


class FakeResult:
    def __init__(self, *, row=None, rows=None, scalar=None) -> None:
        self.row = row
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self):
        return self

    def one(self):
        return self.row

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class FakeSession:
    def __init__(self, *, row=None, rows=None, scalar="event-1") -> None:
        self.row = row
        self.rows = rows or []
        self.scalar = scalar
        self.calls = []
        self.commits = 0

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return FakeResult(row=self.row, rows=self.rows, scalar=self.scalar)

    def commit(self) -> None:
        self.commits += 1


def make_job_row(**overrides):
    row = {
        "id": "job-1",
        "tenant_id": "tenant-1",
        "membership_id": "member-1",
        "job_type": "social.capture",
        "queue_name": "social-ingestion",
        "status": "pending",
        "priority": 10,
        "idempotency_key": "capture:tenant-1:2026-06-01",
        "payload": {"source": "x"},
        "result": None,
        "error_code": None,
        "error_message": None,
        "attempts": 0,
        "max_attempts": 3,
        "run_after": datetime(2026, 6, 1, tzinfo=UTC),
        "locked_at": None,
        "locked_by": None,
        "created_at": datetime(2026, 6, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 1, tzinfo=UTC),
    }
    row.update(overrides)
    return row


def test_retry_delay_uses_capped_exponential_backoff() -> None:
    assert retry_delay_seconds(1) == 30
    assert retry_delay_seconds(2) == 60
    assert retry_delay_seconds(99) == 3600


def test_enqueue_job_uses_tenant_scoped_idempotency() -> None:
    db = FakeSession(row=make_job_row())
    service = JobQueueService(db)

    job = service.enqueue_job(
        tenant_id="tenant-1",
        membership_id="member-1",
        job_type="social.capture",
        queue_name="social-ingestion",
        idempotency_key="capture:tenant-1:2026-06-01",
        payload={"source": "x"},
        priority=10,
    )

    sql, params = db.calls[0]
    assert "ON CONFLICT (tenant_id, job_type, idempotency_key)" in sql
    assert params["tenant_id"] == "tenant-1"
    assert params["idempotency_key"] == "capture:tenant-1:2026-06-01"
    assert job.tenant_id == "tenant-1"
    assert db.commits == 1


def test_queue_metrics_filters_by_tenant() -> None:
    db = FakeSession(
        rows=[
            {"queue_name": "worker-ai", "status": "pending", "total": 2},
            {"queue_name": "worker-ai", "status": "dead_letter", "total": 1},
        ]
    )
    service = JobQueueService(db)

    metrics = service.queue_metrics(tenant_id="tenant-1")

    _, params = db.calls[0]
    assert params == {"tenant_id": "tenant-1"}
    assert [(metric.queue_name, metric.status, metric.count) for metric in metrics] == [
        ("worker-ai", "pending", 2),
        ("worker-ai", "dead_letter", 1),
    ]


def test_record_webhook_event_is_tenant_provider_idempotent() -> None:
    db = FakeSession(scalar="webhook-1")
    service = JobQueueService(db)

    event_id = service.record_webhook_event(
        tenant_id="tenant-1",
        provider="x",
        event_type="mention.created",
        idempotency_key="x:event-123",
        payload={"id": "event-123"},
        headers={"x-signature": "valid"},
        external_event_id="event-123",
        signature_valid=True,
    )

    sql, params = db.calls[0]
    assert "ON CONFLICT (tenant_id, provider, idempotency_key)" in sql
    assert params["tenant_id"] == "tenant-1"
    assert params["provider"] == "x"
    assert event_id == "webhook-1"

