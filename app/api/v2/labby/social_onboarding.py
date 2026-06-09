from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, require_module
from app.domains.jobs.job_service import JobQueueService, JobRecord
from app.domains.social_media.onboarding_service import SocialOnboardingService
from app.schemas.social_onboarding import (
    SocialOnboardingCurrentResponse,
    SocialOnboardingFakeConnectRequest,
    SocialOnboardingJobResponse,
    SocialOnboardingMutationResponse,
    SocialOnboardingSessionCreate,
    SocialOnboardingSessionPatch,
    SocialOnboardingSessionResponse,
    SocialReferenceProfileCreate,
    SocialReferenceProfileResponse,
)

router = APIRouter(prefix="/social/onboarding", tags=["social-onboarding"])
require_social_module = require_module("social_media")


def get_social_onboarding_service(db: Session = Depends(get_db)) -> SocialOnboardingService:
    return SocialOnboardingService(db, job_queue=JobQueueService(db))


@router.get("/current", response_model=SocialOnboardingCurrentResponse)
def get_current_session(
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialOnboardingCurrentResponse:
    session = service.get_current(current=current)
    return SocialOnboardingCurrentResponse(
        session=_session_response(session) if session else None,
    )


@router.post("/sessions", response_model=SocialOnboardingSessionResponse, status_code=201)
def create_session(
    data: SocialOnboardingSessionCreate,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialOnboardingSessionResponse:
    return _session_response(service.create_session(current=current, objective=data.objective))


@router.get("/sessions/{session_id}", response_model=SocialOnboardingSessionResponse)
def get_session(
    session_id: UUID,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialOnboardingSessionResponse:
    return _session_response(service.get_session(current=current, session_id=str(session_id)))


@router.patch("/sessions/{session_id}", response_model=SocialOnboardingSessionResponse)
def update_session(
    session_id: UUID,
    data: SocialOnboardingSessionPatch,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialOnboardingSessionResponse:
    return _session_response(
        service.update_session(
            current=current,
            session_id=str(session_id),
            patch=data.model_dump(exclude_unset=True),
        )
    )


@router.post("/sessions/{session_id}/fake-connect", response_model=SocialOnboardingMutationResponse)
def connect_fake_account(
    session_id: UUID,
    data: SocialOnboardingFakeConnectRequest,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialOnboardingMutationResponse:
    session, job = service.connect_fake_account(
        current=current,
        session_id=str(session_id),
        provider=data.provider,
        handle=data.handle,
        display_name=data.display_name,
        profile_url=data.profile_url,
        followers_count=data.followers_count,
        posts_count=data.posts_count,
        average_engagement_rate=data.average_engagement_rate,
    )
    return SocialOnboardingMutationResponse(
        session=_session_response(session),
        job=_job_response(job),
    )


@router.post(
    "/sessions/{session_id}/references",
    response_model=SocialReferenceProfileResponse,
    status_code=201,
)
def add_reference(
    session_id: UUID,
    data: SocialReferenceProfileCreate,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialReferenceProfileResponse:
    return _reference_response(
        service.add_reference(
            current=current,
            session_id=str(session_id),
            provider=data.provider,
            handle=data.handle,
            label=data.label,
            profile_url=data.profile_url,
        )
    )


@router.post("/sessions/{session_id}/diagnose", response_model=SocialOnboardingMutationResponse)
def enqueue_diagnostic(
    session_id: UUID,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialOnboardingMutationResponse:
    session, job = service.enqueue_diagnostic(current=current, session_id=str(session_id))
    return SocialOnboardingMutationResponse(
        session=_session_response(session),
        job=_job_response(job),
    )


def _session_response(row: dict) -> SocialOnboardingSessionResponse:
    return SocialOnboardingSessionResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        objective=row.get("objective"),
        status=row["status"],
        primary_provider=row.get("primary_provider"),
        connection_mode=row.get("connection_mode") or "none",
        connected_account_handle=row.get("connected_account_handle"),
        connected_account_name=row.get("connected_account_name"),
        profile_url=row.get("profile_url"),
        progress_steps=list(row.get("progress_steps") or []),
        profile_snapshot=dict(row.get("profile_snapshot") or {}),
        analysis_report=row.get("analysis_report"),
        analysis_version=row["analysis_version"],
        references=[_reference_response(reference) for reference in row.get("references", [])],
        error_code=row.get("error_code"),
        error_message=row.get("error_message"),
        analysis_started_at=row.get("analysis_started_at"),
        analysis_completed_at=row.get("analysis_completed_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _reference_response(row: dict) -> SocialReferenceProfileResponse:
    return SocialReferenceProfileResponse(
        id=row["id"],
        provider=row["provider"],
        handle=row["handle"],
        label=row.get("label"),
        profile_url=row.get("profile_url"),
        status=row["status"],
        created_at=row["created_at"],
    )


def _job_response(job: JobRecord) -> SocialOnboardingJobResponse:
    return SocialOnboardingJobResponse(
        id=UUID(str(job.id)),
        job_type=job.job_type,
        queue_name=job.queue_name,
        status=job.status,
        idempotency_key=job.idempotency_key,
    )
