from dataclasses import replace
from datetime import UTC, datetime

from app.domains.jobs.job_service import JobRecord
from app.domains.jobs.registry import JobHandlerRegistry, RetryableJobError
from app.jobs.runner import process_due_jobs


class FakeJobService:
    def __init__(self, jobs: list[JobRecord]) -> None:
        self.jobs = jobs
        self.completed = []
        self.failed = []
        self.reaped = []

    def requeue_stale_running_jobs(
        self,
        *,
        stale_after_seconds: int,
        queue_name: str | None = None,
        limit: int = 50,
    ):
        return self.reaped

    def claim_due_job(self, *, worker_name: str, queue_name: str | None = None):
        if not self.jobs:
            return None
        return self.jobs.pop(0)

    def start_attempt(self, *, job: JobRecord, worker_name: str) -> str:
        return f"attempt-{job.id}"

    def complete_job(self, *, job_id: str, attempt_id: str, result=None):
        self.completed.append((job_id, attempt_id, result))

    def fail_job(
        self,
        *,
        job_id: str,
        attempt_id: str,
        error_code: str,
        error_message: str,
        permanent: bool = False,
    ):
        status = "dead_letter" if permanent else "retrying"
        self.failed.append((job_id, attempt_id, error_code, error_message, permanent))
        return replace(make_job(job_id=job_id), status=status)


def make_job(job_id: str = "job-1", job_type: str = "test.success") -> JobRecord:
    return JobRecord(
        id=job_id,
        tenant_id="tenant-1",
        membership_id="member-1",
        job_type=job_type,
        queue_name="worker-ai",
        status="running",
        priority=0,
        idempotency_key=f"{job_type}:1",
        payload={"value": 42},
        result=None,
        error_code=None,
        error_message=None,
        attempts=1,
        max_attempts=3,
        run_after=datetime(2026, 6, 1, tzinfo=UTC),
        locked_at=None,
        locked_by=None,
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
        updated_at=datetime(2026, 6, 1, tzinfo=UTC),
    )


def test_process_due_jobs_runs_handler_and_completes_job() -> None:
    registry = JobHandlerRegistry()

    @registry.register("test.success")
    def handler(context):
        assert context.tenant_id == "tenant-1"
        assert context.payload == {"value": 42}
        return {"ok": True}

    service = FakeJobService([make_job()])

    result = process_due_jobs(service=service, worker_name="worker-1", registry=registry)

    assert result == {"reaped": 0, "processed": 1, "succeeded": 1, "retried": 0, "dead_letter": 0}
    assert service.completed == [("job-1", "attempt-job-1", {"ok": True})]


def test_process_due_jobs_retries_retryable_errors() -> None:
    registry = JobHandlerRegistry()

    @registry.register("test.retry")
    def handler(context):
        raise RetryableJobError("provider timeout")

    service = FakeJobService([make_job(job_type="test.retry")])

    result = process_due_jobs(service=service, worker_name="worker-1", registry=registry)

    assert result == {"reaped": 0, "processed": 1, "succeeded": 0, "retried": 1, "dead_letter": 0}
    assert service.failed[0][2] == "RetryableJobError"
    assert service.failed[0][4] is False


def test_process_due_jobs_dead_letters_missing_handler() -> None:
    service = FakeJobService([make_job(job_type="test.missing")])

    result = process_due_jobs(
        service=service,
        worker_name="worker-1",
        registry=JobHandlerRegistry(),
    )

    assert result == {"reaped": 0, "processed": 1, "succeeded": 0, "retried": 0, "dead_letter": 1}
    assert service.failed[0][2] == "handler_not_found"
    assert service.failed[0][4] is True


def test_process_due_jobs_reaps_stale_running_jobs_before_claiming() -> None:
    registry = JobHandlerRegistry()
    service = FakeJobService([])
    service.reaped = [make_job(job_id="stale-job", job_type="test.stale")]

    result = process_due_jobs(
        service=service,
        worker_name="worker-1",
        registry=registry,
        stale_after_seconds=900,
        reaper_limit=10,
    )

    assert result == {"reaped": 1, "processed": 0, "succeeded": 0, "retried": 0, "dead_letter": 0}
