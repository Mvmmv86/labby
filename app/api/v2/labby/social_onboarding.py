from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, require_module
from app.domains.jobs.job_service import JobQueueService, JobRecord
from app.domains.social_media.onboarding_service import SocialOnboardingService
from app.schemas.social_onboarding import (
    SocialActionPlanItemPatch,
    SocialActionPlanItemResponse,
    SocialActionPlanResponse,
    SocialCalendarEntryPatch,
    SocialCalendarEntryResponse,
    SocialContentDraftPatch,
    SocialContentDraftResponse,
    SocialOnboardingCurrentResponse,
    SocialOnboardingFakeConnectRequest,
    SocialOnboardingJobResponse,
    SocialOnboardingMutationResponse,
    SocialOnboardingPhylloCompleteRequest,
    SocialOnboardingPhylloConnectTokenResponse,
    SocialOnboardingSessionCreate,
    SocialOnboardingSessionPatch,
    SocialOnboardingSessionResponse,
    SocialReferenceProfileCreate,
    SocialReferenceProfileResponse,
    SocialReferenceProfileSyncResponse,
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
    "/sessions/{session_id}/phyllo/connect-token",
    response_model=SocialOnboardingPhylloConnectTokenResponse,
)
def create_phyllo_connect_token(
    session_id: UUID,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialOnboardingPhylloConnectTokenResponse:
    return SocialOnboardingPhylloConnectTokenResponse(
        **service.create_phyllo_connect_token(
            current=current,
            session_id=str(session_id),
        )
    )


@router.post(
    "/sessions/{session_id}/phyllo/complete",
    response_model=SocialOnboardingMutationResponse,
)
def complete_phyllo_connection(
    session_id: UUID,
    data: SocialOnboardingPhylloCompleteRequest,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialOnboardingMutationResponse:
    session, job = service.complete_phyllo_connection(
        current=current,
        session_id=str(session_id),
        phyllo_user_id=data.user_id,
        account_id=data.account_id,
        work_platform_id=data.work_platform_id,
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


@router.post(
    "/sessions/{session_id}/references/{reference_id}/sync",
    response_model=SocialReferenceProfileSyncResponse,
)
def sync_reference(
    session_id: UUID,
    reference_id: UUID,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialReferenceProfileSyncResponse:
    reference, job = service.enqueue_reference_sync(
        current=current,
        session_id=str(session_id),
        reference_id=str(reference_id),
    )
    return SocialReferenceProfileSyncResponse(
        reference=_reference_response(reference),
        job=_job_response(job) if job else None,
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


@router.post(
    "/sessions/{session_id}/specialist-analysis",
    response_model=SocialOnboardingMutationResponse,
)
def enqueue_specialist_analysis(
    session_id: UUID,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialOnboardingMutationResponse:
    session, job = service.enqueue_specialist_analysis(
        current=current,
        session_id=str(session_id),
    )
    return SocialOnboardingMutationResponse(
        session=_session_response(session),
        job=_job_response(job),
    )


@router.get(
    "/sessions/{session_id}/action-plan",
    response_model=SocialActionPlanResponse,
)
def get_action_plan(
    session_id: UUID,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialActionPlanResponse:
    return _action_plan_response(
        service.get_action_plan(current=current, session_id=str(session_id)),
    )


@router.post(
    "/sessions/{session_id}/action-plan/generate",
    response_model=SocialActionPlanResponse,
)
def generate_action_plan(
    session_id: UUID,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialActionPlanResponse:
    return _action_plan_response(
        service.generate_action_plan(current=current, session_id=str(session_id)),
    )


@router.patch(
    "/action-plan/items/{item_id}",
    response_model=SocialActionPlanResponse,
)
def update_action_plan_item(
    item_id: UUID,
    data: SocialActionPlanItemPatch,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialActionPlanResponse:
    return _action_plan_response(
        service.update_action_plan_item(
            current=current,
            item_id=str(item_id),
            patch=data.model_dump(exclude_unset=True),
        )
    )


@router.patch(
    "/action-plan/calendar/{entry_id}",
    response_model=SocialActionPlanResponse,
)
def update_calendar_entry(
    entry_id: UUID,
    data: SocialCalendarEntryPatch,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialActionPlanResponse:
    return _action_plan_response(
        service.update_calendar_entry(
            current=current,
            entry_id=str(entry_id),
            patch=data.model_dump(exclude_unset=True),
        )
    )


@router.get(
    "/action-plan/calendar/{entry_id}/drafts/current",
    response_model=SocialContentDraftResponse,
)
def get_current_content_draft(
    entry_id: UUID,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialContentDraftResponse:
    return _content_draft_response(
        service.get_current_content_draft(current=current, entry_id=str(entry_id))
    )


@router.post(
    "/action-plan/calendar/{entry_id}/drafts/generate",
    response_model=SocialContentDraftResponse,
)
def generate_content_draft(
    entry_id: UUID,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialContentDraftResponse:
    return _content_draft_response(
        service.generate_content_draft(current=current, entry_id=str(entry_id))
    )


@router.patch(
    "/action-plan/calendar/drafts/{draft_id}",
    response_model=SocialContentDraftResponse,
)
def update_content_draft(
    draft_id: UUID,
    data: SocialContentDraftPatch,
    current: CurrentMembership = Depends(require_social_module),
    service: SocialOnboardingService = Depends(get_social_onboarding_service),
) -> SocialContentDraftResponse:
    return _content_draft_response(
        service.update_content_draft(
            current=current,
            draft_id=str(draft_id),
            patch=data.model_dump(exclude_unset=True),
        )
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
        public_reference_profile_id=row.get("public_reference_profile_id"),
        provider=row["provider"],
        handle=row["handle"],
        label=row.get("label"),
        profile_url=row.get("profile_url"),
        status=row["status"],
        sync_status=row.get("sync_status") or "manual_pending",
        global_sync_status=row.get("global_sync_status"),
        public_contents_count=int(row.get("public_contents_count") or 0),
        last_synced_at=row.get("last_synced_at"),
        global_last_synced_at=row.get("global_last_synced_at"),
        data_truth=row.get("data_truth"),
        comparison_summary=row.get("comparison_summary"),
        created_at=row["created_at"],
    )


def _action_plan_response(row: dict) -> SocialActionPlanResponse:
    return SocialActionPlanResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        onboarding_session_id=row["onboarding_session_id"],
        title=row["title"],
        summary=row.get("summary"),
        status=row["status"],
        source_analysis_version=row["source_analysis_version"],
        source_specialist_version=row.get("source_specialist_version"),
        plan_version=row["plan_version"],
        metadata_json=row.get("metadata_json"),
        items=[_action_item_response(item) for item in row.get("items", [])],
        calendar_entries=[
            _calendar_entry_response(entry) for entry in row.get("calendar_entries", [])
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _action_item_response(row: dict) -> SocialActionPlanItemResponse:
    return SocialActionPlanItemResponse(
        id=row["id"],
        position=row["position"],
        title=row["title"],
        description=row["description"],
        why_it_matters=row.get("why_it_matters"),
        how_to_execute=row.get("how_to_execute"),
        expected_signal=row.get("expected_signal"),
        measurement=row.get("measurement"),
        evidence=row.get("evidence"),
        priority=row["priority"],
        status=row["status"],
        source_json=row.get("source_json"),
        notes=row.get("notes"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _calendar_entry_response(row: dict) -> SocialCalendarEntryResponse:
    return SocialCalendarEntryResponse(
        id=row["id"],
        action_item_id=row.get("action_item_id"),
        scheduled_at=row["scheduled_at"],
        day_index=row["day_index"],
        title=row["title"],
        format=row["format"],
        channel=row["channel"],
        status=row["status"],
        theme=row.get("theme"),
        hook=row.get("hook"),
        caption_outline=row.get("caption_outline"),
        cta=row.get("cta"),
        evidence=row.get("evidence"),
        objective=row.get("objective"),
        source_reference_handle=row.get("source_reference_handle"),
        metrics_goal_json=row.get("metrics_goal_json"),
        metadata_json=row.get("metadata_json"),
        current_draft=_content_draft_response(row["current_draft"])
        if row.get("current_draft")
        else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _content_draft_response(row: dict) -> SocialContentDraftResponse:
    return SocialContentDraftResponse(
        id=row["id"],
        calendar_entry_id=row["calendar_entry_id"],
        action_plan_id=row["action_plan_id"],
        onboarding_session_id=row["onboarding_session_id"],
        draft_version=row["draft_version"],
        status=row["status"],
        format=row["format"],
        channel=row["channel"],
        title=row["title"],
        angle=row.get("angle"),
        hook=row.get("hook"),
        caption=row.get("caption"),
        cta=row.get("cta"),
        visual_direction=row.get("visual_direction"),
        script_json=list(row.get("script_json") or []),
        production_checklist_json=list(row.get("production_checklist_json") or []),
        evidence_json=row.get("evidence_json"),
        metadata_json=row.get("metadata_json"),
        is_current=bool(row.get("is_current")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _job_response(job: JobRecord) -> SocialOnboardingJobResponse:
    return SocialOnboardingJobResponse(
        id=UUID(str(job.id)),
        job_type=job.job_type,
        queue_name=job.queue_name,
        status=job.status,
        idempotency_key=job.idempotency_key,
    )
