import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class JobRecord:
    id: str
    tenant_id: str
    membership_id: str | None
    job_type: str
    queue_name: str
    status: str
    priority: int
    idempotency_key: str
    payload: dict[str, Any]
    result: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    attempts: int
    max_attempts: int
    run_after: datetime
    locked_at: datetime | None
    locked_by: str | None
    created_at: datetime | None
    updated_at: datetime | None


@dataclass(frozen=True)
class QueueMetric:
    queue_name: str
    status: str
    count: int


class JobQueueService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def enqueue_job(
        self,
        *,
        tenant_id: str,
        job_type: str,
        queue_name: str,
        idempotency_key: str,
        payload: Mapping[str, Any] | None = None,
        membership_id: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        run_after: datetime | None = None,
    ) -> JobRecord:
        row = self.db.execute(
            text(
                """
                INSERT INTO jobs (
                  tenant_id,
                  membership_id,
                  job_type,
                  queue_name,
                  idempotency_key,
                  payload,
                  priority,
                  max_attempts,
                  run_after
                )
                VALUES (
                  :tenant_id,
                  :membership_id,
                  :job_type,
                  :queue_name,
                  :idempotency_key,
                  CAST(:payload AS jsonb),
                  :priority,
                  :max_attempts,
                  :run_after
                )
                ON CONFLICT (tenant_id, job_type, idempotency_key)
                DO UPDATE SET idempotency_key = jobs.idempotency_key
                RETURNING *
                """
            ),
            {
                "tenant_id": tenant_id,
                "membership_id": membership_id,
                "job_type": job_type,
                "queue_name": queue_name,
                "idempotency_key": idempotency_key,
                "payload": json.dumps(dict(payload or {})),
                "priority": priority,
                "max_attempts": max_attempts,
                "run_after": run_after or datetime.now(UTC),
            },
        ).mappings().one()
        self.db.commit()
        return _job_from_row(row)

    def claim_due_job(
        self,
        *,
        worker_name: str,
        queue_name: str | None = None,
    ) -> JobRecord | None:
        queue_filter = "AND queue_name = :queue_name" if queue_name else ""
        row = self.db.execute(
            text(
                f"""
                WITH next_job AS (
                  SELECT id
                  FROM jobs
                  WHERE status IN ('pending', 'retrying')
                    AND run_after <= NOW()
                    {queue_filter}
                  ORDER BY priority DESC, run_after ASC, created_at ASC
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
                )
                UPDATE jobs j
                SET status = 'running',
                    attempts = attempts + 1,
                    locked_at = NOW(),
                    locked_by = :worker_name,
                    updated_at = NOW()
                FROM next_job
                WHERE j.id = next_job.id
                RETURNING j.*
                """
            ),
            {"worker_name": worker_name, "queue_name": queue_name},
        ).mappings().first()
        self.db.commit()
        return _job_from_row(row) if row else None

    def start_attempt(self, *, job: JobRecord, worker_name: str) -> str:
        attempt_id = self.db.execute(
            text(
                """
                INSERT INTO job_attempts (
                  job_id,
                  tenant_id,
                  attempt_number,
                  status,
                  worker_name
                )
                VALUES (
                  :job_id,
                  :tenant_id,
                  :attempt_number,
                  'running',
                  :worker_name
                )
                RETURNING id
                """
            ),
            {
                "job_id": job.id,
                "tenant_id": job.tenant_id,
                "attempt_number": job.attempts,
                "worker_name": worker_name,
            },
        ).scalar_one()
        self.db.commit()
        return str(attempt_id)

    def complete_job(
        self,
        *,
        job_id: str,
        attempt_id: str,
        result: Mapping[str, Any] | None = None,
    ) -> JobRecord:
        result_json = json.dumps(dict(result or {}))
        row = self.db.execute(
            text(
                """
                UPDATE jobs
                SET status = 'succeeded',
                    result = CAST(:result AS jsonb),
                    error_code = NULL,
                    error_message = NULL,
                    locked_at = NULL,
                    locked_by = NULL,
                    updated_at = NOW()
                WHERE id = :job_id
                RETURNING *
                """
            ),
            {"job_id": job_id, "result": result_json},
        ).mappings().one()
        self.db.execute(
            text(
                """
                UPDATE job_attempts
                SET status = 'succeeded',
                    result = CAST(:result AS jsonb),
                    finished_at = NOW()
                WHERE id = :attempt_id
                """
            ),
            {"attempt_id": attempt_id, "result": result_json},
        )
        self.db.commit()
        return _job_from_row(row)

    def fail_job(
        self,
        *,
        job_id: str,
        attempt_id: str,
        error_code: str,
        error_message: str,
        permanent: bool = False,
    ) -> JobRecord:
        current = self.get_job(job_id)
        status = (
            "dead_letter"
            if permanent or current.attempts >= current.max_attempts
            else "retrying"
        )
        next_run = datetime.now(UTC)
        if status == "retrying":
            next_run += timedelta(seconds=retry_delay_seconds(current.attempts))

        row = self.db.execute(
            text(
                """
                UPDATE jobs
                SET status = :status,
                    run_after = :run_after,
                    error_code = :error_code,
                    error_message = :error_message,
                    locked_at = NULL,
                    locked_by = NULL,
                    updated_at = NOW()
                WHERE id = :job_id
                RETURNING *
                """
            ),
            {
                "job_id": job_id,
                "status": status,
                "run_after": next_run,
                "error_code": error_code,
                "error_message": error_message[:2000],
            },
        ).mappings().one()
        self.db.execute(
            text(
                """
                UPDATE job_attempts
                SET status = 'failed',
                    error_code = :error_code,
                    error_message = :error_message,
                    finished_at = NOW()
                WHERE id = :attempt_id
                """
            ),
            {
                "attempt_id": attempt_id,
                "error_code": error_code,
                "error_message": error_message[:2000],
            },
        )
        self.db.commit()
        return _job_from_row(row)

    def get_job(self, job_id: str) -> JobRecord:
        row = self.db.execute(
            text("SELECT * FROM jobs WHERE id = :job_id"),
            {"job_id": job_id},
        ).mappings().one()
        return _job_from_row(row)

    def queue_metrics(self, *, tenant_id: str) -> list[QueueMetric]:
        rows = self.db.execute(
            text(
                """
                SELECT queue_name, status, COUNT(*) AS total
                FROM jobs
                WHERE tenant_id = :tenant_id
                GROUP BY queue_name, status
                ORDER BY queue_name ASC, status ASC
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().all()
        return [
            QueueMetric(
                queue_name=row["queue_name"],
                status=row["status"],
                count=int(row["total"] or 0),
            )
            for row in rows
        ]

    def enqueue_outbox_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        idempotency_key: str,
        aggregate_type: str,
        payload: Mapping[str, Any] | None = None,
        aggregate_id: str | None = None,
        membership_id: str | None = None,
    ) -> str:
        event_id = self.db.execute(
            text(
                """
                INSERT INTO outbox_events (
                  tenant_id,
                  membership_id,
                  aggregate_type,
                  aggregate_id,
                  event_type,
                  idempotency_key,
                  payload
                )
                VALUES (
                  :tenant_id,
                  :membership_id,
                  :aggregate_type,
                  :aggregate_id,
                  :event_type,
                  :idempotency_key,
                  CAST(:payload AS jsonb)
                )
                ON CONFLICT (tenant_id, event_type, idempotency_key)
                DO UPDATE SET idempotency_key = outbox_events.idempotency_key
                RETURNING id
                """
            ),
            {
                "tenant_id": tenant_id,
                "membership_id": membership_id,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "event_type": event_type,
                "idempotency_key": idempotency_key,
                "payload": json.dumps(dict(payload or {})),
            },
        ).scalar_one()
        self.db.commit()
        return str(event_id)

    def record_webhook_event(
        self,
        *,
        tenant_id: str,
        provider: str,
        event_type: str,
        idempotency_key: str,
        payload: Mapping[str, Any],
        headers: Mapping[str, Any] | None = None,
        external_event_id: str | None = None,
        signature_valid: bool = False,
    ) -> str:
        event_id = self.db.execute(
            text(
                """
                INSERT INTO webhook_events (
                  tenant_id,
                  provider,
                  external_event_id,
                  event_type,
                  idempotency_key,
                  signature_valid,
                  headers,
                  payload
                )
                VALUES (
                  :tenant_id,
                  :provider,
                  :external_event_id,
                  :event_type,
                  :idempotency_key,
                  :signature_valid,
                  CAST(:headers AS jsonb),
                  CAST(:payload AS jsonb)
                )
                ON CONFLICT (tenant_id, provider, idempotency_key)
                DO UPDATE SET idempotency_key = webhook_events.idempotency_key
                RETURNING id
                """
            ),
            {
                "tenant_id": tenant_id,
                "provider": provider,
                "external_event_id": external_event_id,
                "event_type": event_type,
                "idempotency_key": idempotency_key,
                "signature_valid": signature_valid,
                "headers": json.dumps(dict(headers or {})),
                "payload": json.dumps(dict(payload)),
            },
        ).scalar_one()
        self.db.commit()
        return str(event_id)

    def record_rate_limit_event(
        self,
        *,
        tenant_id: str,
        provider: str,
        rate_limit_key: str,
        action: str,
        outcome: str,
        retry_after: datetime | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> str:
        event_id = self.db.execute(
            text(
                """
                INSERT INTO rate_limit_events (
                  tenant_id,
                  provider,
                  rate_limit_key,
                  action,
                  outcome,
                  retry_after,
                  metadata_json
                )
                VALUES (
                  :tenant_id,
                  :provider,
                  :rate_limit_key,
                  :action,
                  :outcome,
                  :retry_after,
                  CAST(:metadata_json AS jsonb)
                )
                RETURNING id
                """
            ),
            {
                "tenant_id": tenant_id,
                "provider": provider,
                "rate_limit_key": rate_limit_key,
                "action": action,
                "outcome": outcome,
                "retry_after": retry_after,
                "metadata_json": json.dumps(dict(metadata or {})),
            },
        ).scalar_one()
        self.db.commit()
        return str(event_id)


def retry_delay_seconds(attempts: int) -> int:
    return min(3600, 30 * (2 ** max(attempts - 1, 0)))


def _job_from_row(row: Mapping[str, Any]) -> JobRecord:
    payload = row["payload"]
    result = row["result"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if isinstance(result, str):
        result = json.loads(result)

    return JobRecord(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        membership_id=str(row["membership_id"]) if row["membership_id"] else None,
        job_type=row["job_type"],
        queue_name=row["queue_name"],
        status=row["status"],
        priority=row["priority"],
        idempotency_key=row["idempotency_key"],
        payload=dict(payload or {}),
        result=dict(result) if result else None,
        error_code=row["error_code"],
        error_message=row["error_message"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        run_after=row["run_after"],
        locked_at=row["locked_at"],
        locked_by=row["locked_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
