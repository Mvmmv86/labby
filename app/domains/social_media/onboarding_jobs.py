from app.core.database import SessionLocal
from app.domains.jobs.job_service import JobQueueService
from app.domains.jobs.registry import JobExecutionContext, PermanentJobError, job_handlers
from app.domains.social_media.onboarding_service import (
    SOCIAL_ONBOARDING_DIAGNOSE_JOB,
    SocialOnboardingService,
)


@job_handlers.register(SOCIAL_ONBOARDING_DIAGNOSE_JOB)
def diagnose_social_onboarding(context: JobExecutionContext) -> dict:
    session_id = context.payload.get("session_id")
    if not session_id:
        raise PermanentJobError("session_id ausente")
    analysis_version = context.payload.get("analysis_version")
    if analysis_version is None:
        raise PermanentJobError("analysis_version ausente")
    try:
        version = int(analysis_version)
    except (TypeError, ValueError) as exc:
        raise PermanentJobError("analysis_version invalida") from exc

    with SessionLocal() as db:
        service = SocialOnboardingService(db, job_queue=JobQueueService(db))
        try:
            return service.run_diagnostic(
                tenant_id=context.tenant_id,
                session_id=str(session_id),
                analysis_version=version,
            )
        except Exception as exc:
            db.rollback()
            if isinstance(exc, ValueError):
                service.mark_diagnostic_failed(
                    tenant_id=context.tenant_id,
                    session_id=str(session_id),
                    analysis_version=version,
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                )
                raise PermanentJobError(str(exc)) from exc
            raise
