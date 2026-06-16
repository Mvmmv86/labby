import logging
from typing import Any

from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.domains.jobs.job_service import JobQueueService, JobRecord
from app.domains.jobs.registry import (
    JobExecutionContext,
    JobHandlerRegistry,
    PermanentJobError,
    RetryableJobError,
    job_handlers,
)
from app.domains.sales import campaign_jobs as _campaign_jobs  # noqa: F401
from app.domains.sales import outbound_jobs as _outbound_jobs  # noqa: F401
from app.domains.sales import webhook_jobs as _webhook_jobs  # noqa: F401
from app.domains.social_media import news_jobs as _news_jobs  # noqa: F401
from app.domains.social_media import onboarding_jobs as _onboarding_jobs  # noqa: F401
from app.domains.social_media.onboarding_service import SocialOnboardingService

logger = logging.getLogger(__name__)


def process_due_jobs(
    *,
    service: JobQueueService,
    worker_name: str,
    registry: JobHandlerRegistry = job_handlers,
    queue_name: str | None = None,
    limit: int = 10,
    stale_after_seconds: int | None = None,
    reaper_limit: int = 50,
) -> dict[str, int]:
    reaped = 0
    if stale_after_seconds is not None:
        reaped_jobs = service.requeue_stale_running_jobs(
            stale_after_seconds=stale_after_seconds,
            queue_name=queue_name,
            limit=reaper_limit,
        )
        reaped = len(reaped_jobs)

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
        "reaped": reaped,
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
    settings = get_settings()
    with SessionLocal() as db:
        service = JobQueueService(db)
        return process_due_jobs(
            service=service,
            worker_name=worker_name,
            queue_name=queue_name,
            limit=limit,
            stale_after_seconds=settings.job_running_timeout_seconds,
            reaper_limit=settings.job_reaper_batch_size,
        )


@celery_app.task(name="labby.jobs.cleanup_operational_history")
def cleanup_operational_history() -> dict[str, int]:
    settings = get_settings()
    with SessionLocal() as db:
        result = JobQueueService(db).cleanup_operational_history(
            rate_limit_retention_days=settings.rate_limit_events_retention_days,
            dispatch_attempt_retention_days=settings.sales_dispatch_attempt_retention_days,
            limit=settings.operational_history_cleanup_batch_size,
        )
    return {
        "rate_limit_events_deleted": result.rate_limit_events_deleted,
        "dispatch_attempts_deleted": result.dispatch_attempts_deleted,
    }


@celery_app.task(name="labby.social_onboarding.reconcile_abandoned_analyses")
def reconcile_abandoned_social_onboarding_analyses() -> dict[str, int]:
    settings = get_settings()
    with SessionLocal() as db:
        service = SocialOnboardingService(db, job_queue=JobQueueService(db))
        public_reference_rows: list[dict[str, Any]] = []
        orphaned_public_reference_rows: list[dict[str, Any]] = []
        phyllo_rows: list[dict[str, Any]] = []
        abandoned_rows: list[dict[str, Any]] = []
        errors = 0

        try:
            public_reference_rows = service.reconcile_stale_public_reference_syncs(
                stale_after_minutes=settings.apify_public_reference_syncing_timeout_minutes,
                limit=settings.apify_public_reference_reaper_batch_size,
            )
        except Exception:
            errors += 1
            db.rollback()
            logger.warning("social_onboarding_public_reference_reaper_failed", exc_info=True)

        try:
            orphaned_public_reference_rows = service.cleanup_orphaned_public_references(
                retention_days=settings.social_public_reference_orphan_retention_days,
                limit=settings.social_public_reference_cleanup_batch_size,
            )
        except Exception:
            errors += 1
            db.rollback()
            logger.warning("social_onboarding_public_reference_cleanup_failed", exc_info=True)

        try:
            phyllo_rows = service.reconcile_phyllo_connecting_sessions(
                limit=settings.social_onboarding_reconciler_batch_size,
            )
        except Exception:
            errors += 1
            db.rollback()
            logger.warning("social_onboarding_phyllo_reconciler_failed", exc_info=True)

        try:
            abandoned_rows = service.reconcile_abandoned_analyses(
                limit=settings.social_onboarding_reconciler_batch_size,
            )
        except Exception:
            errors += 1
            db.rollback()
            logger.warning("social_onboarding_analysis_reconciler_failed", exc_info=True)
    return {
        "public_reference_failed": len(public_reference_rows),
        "public_reference_orphans_deleted": len(orphaned_public_reference_rows),
        "phyllo_reconciled": len(phyllo_rows),
        "failed": len(abandoned_rows),
        "errors": errors,
    }


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
