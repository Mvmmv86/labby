from typing import Any

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.domains.jobs.job_service import JobQueueService, JobRecord
from app.domains.jobs.registry import (
    JobExecutionContext,
    JobHandlerRegistry,
    PermanentJobError,
    RetryableJobError,
    job_handlers,
)


def process_due_jobs(
    *,
    service: JobQueueService,
    worker_name: str,
    registry: JobHandlerRegistry = job_handlers,
    queue_name: str | None = None,
    limit: int = 10,
) -> dict[str, int]:
    processed = 0
    succeeded = 0
    retried = 0
    dead_letter = 0

    for _ in range(max(limit, 0)):
        job = service.claim_due_job(worker_name=worker_name, queue_name=queue_name)
        if job is None:
            break

        processed += 1
        attempt_id = service.start_attempt(job=job, worker_name=worker_name)
        handler = registry.get(job.job_type)
        if handler is None:
            failed = service.fail_job(
                job_id=job.id,
                attempt_id=attempt_id,
                error_code="handler_not_found",
                error_message=f"Nenhum handler registrado para {job.job_type}",
                permanent=True,
            )
            dead_letter += int(failed.status == "dead_letter")
            continue

        try:
            result = handler(_execution_context(job))
        except PermanentJobError as exc:
            failed = service.fail_job(
                job_id=job.id,
                attempt_id=attempt_id,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                permanent=True,
            )
            dead_letter += int(failed.status == "dead_letter")
        except RetryableJobError as exc:
            failed = service.fail_job(
                job_id=job.id,
                attempt_id=attempt_id,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                permanent=False,
            )
            retried += int(failed.status == "retrying")
            dead_letter += int(failed.status == "dead_letter")
        except Exception as exc:
            failed = service.fail_job(
                job_id=job.id,
                attempt_id=attempt_id,
                error_code=exc.__class__.__name__,
                error_message=str(exc),
                permanent=False,
            )
            retried += int(failed.status == "retrying")
            dead_letter += int(failed.status == "dead_letter")
        else:
            service.complete_job(
                job_id=job.id,
                attempt_id=attempt_id,
                result=dict(result or {}),
            )
            succeeded += 1

    return {
        "processed": processed,
        "succeeded": succeeded,
        "retried": retried,
        "dead_letter": dead_letter,
    }


@celery_app.task(name="labby.jobs.dispatch_due_jobs", bind=True)
def dispatch_due_jobs(
    self,
    queue_name: str | None = None,
    limit: int = 10,
) -> dict[str, int]:
    worker_name = _worker_name(self.request)
    with SessionLocal() as db:
        service = JobQueueService(db)
        return process_due_jobs(
            service=service,
            worker_name=worker_name,
            queue_name=queue_name,
            limit=limit,
        )


def _execution_context(job: JobRecord) -> JobExecutionContext:
    return JobExecutionContext(
        job_id=job.id,
        tenant_id=job.tenant_id,
        membership_id=job.membership_id,
        job_type=job.job_type,
        queue_name=job.queue_name,
        payload=job.payload,
        attempts=job.attempts,
    )


def _worker_name(request: Any) -> str:
    hostname = getattr(request, "hostname", None)
    return hostname or "labby-worker"
