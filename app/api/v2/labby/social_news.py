from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.jobs.job_service import JobQueueService, JobRecord
from app.domains.social_media.news_service import SocialNewsService
from app.schemas.social_news import (
    EnqueuedJobResponse,
    SocialNewsCurationRequest,
    SocialNewsCurationResponse,
    SocialNewsDispatchConfigResponse,
    SocialNewsDispatchEnqueuedResponse,
    SocialNewsDispatchesResponse,
    SocialNewsDispatchResponse,
    SocialNewsItemResponse,
    SocialNewsItemsResponse,
    SocialNewsJobRequest,
    SocialNewsJobResponse,
    SocialNewsRunCreate,
    SocialNewsRunCreatedResponse,
    SocialNewsRunResponse,
    SocialNewsRunsResponse,
    SocialNewsSegmentCreate,
    SocialNewsSegmentResponse,
    SocialNewsSegmentsResponse,
    SocialNewsSourceCreate,
    SocialNewsSourceResponse,
    SocialNewsSourcesResponse,
    SocialNewsStageDecisionRequest,
    SocialNewsSubscriberCreate,
    SocialNewsSubscriberCreatedResponse,
    SocialNewsSubscriberResponse,
    SocialNewsSubscribersResponse,
    SocialNewsUnsubscribeResponse,
)

router = APIRouter(prefix="/social/news", tags=["social-news"])


def get_social_news_service(db: Session = Depends(get_db)) -> SocialNewsService:
    return SocialNewsService(db, job_queue=JobQueueService(db))


@router.get("/segments", response_model=SocialNewsSegmentsResponse)
def list_segments(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSegmentsResponse:
    rows = service.list_segments(
        current=current,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return SocialNewsSegmentsResponse(segments=[SocialNewsSegmentResponse(**row) for row in rows])


@router.post(
    "/segments",
    response_model=SocialNewsSegmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_segment(
    data: SocialNewsSegmentCreate,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSegmentResponse:
    row = service.create_segment(
        current=current,
        slug=data.slug,
        name=data.name,
        description=data.description,
        base_knowledge=data.base_knowledge,
        disclaimer=data.disclaimer,
        min_engagement_score=data.min_engagement_score,
        config=data.config,
    )
    return SocialNewsSegmentResponse(**row)


@router.get("/segments/{segment_id}/sources", response_model=SocialNewsSourcesResponse)
def list_sources(
    segment_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSourcesResponse:
    rows = service.list_sources(current=current, segment_id=segment_id)
    return SocialNewsSourcesResponse(sources=[SocialNewsSourceResponse(**row) for row in rows])


@router.post(
    "/segments/{segment_id}/sources",
    response_model=SocialNewsSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_source(
    segment_id: str,
    data: SocialNewsSourceCreate,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSourceResponse:
    row = service.add_source(
        current=current,
        segment_id=segment_id,
        source_type=data.source_type,
        value=data.value,
        provider=data.provider,
        min_likes=data.min_likes,
        min_reposts=data.min_reposts,
        min_replies=data.min_replies,
        min_impressions=data.min_impressions,
        metadata=data.metadata,
    )
    return SocialNewsSourceResponse(**row)


@router.post(
    "/runs",
    response_model=SocialNewsRunCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_run(
    data: SocialNewsRunCreate,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsRunCreatedResponse:
    run, job = service.start_run(
        current=current,
        segment_id=str(data.segment_id),
        idempotency_key=data.idempotency_key,
        run_type=data.run_type,
    )
    return SocialNewsRunCreatedResponse(
        run=SocialNewsRunResponse(**run),
        job=_job_response(job),
    )


@router.get("/runs", response_model=SocialNewsRunsResponse)
def list_runs(
    segment_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsRunsResponse:
    rows = service.list_runs(
        current=current,
        segment_id=segment_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return SocialNewsRunsResponse(runs=[SocialNewsRunResponse(**row) for row in rows])


@router.get("/runs/{run_id}/items", response_model=SocialNewsItemsResponse)
def list_run_items(
    run_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsItemsResponse:
    rows = service.list_run_items(
        current=current,
        run_id=run_id,
        status=status_filter,
        limit=limit,
    )
    return SocialNewsItemsResponse(items=[SocialNewsItemResponse(**row) for row in rows])


@router.get("/items", response_model=SocialNewsItemsResponse)
def list_items(
    segment_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsItemsResponse:
    rows = service.list_items(
        current=current,
        segment_id=segment_id,
        run_id=run_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return SocialNewsItemsResponse(items=[SocialNewsItemResponse(**row) for row in rows])


@router.get("/curation/stage1", response_model=SocialNewsItemsResponse)
def list_curation_stage1_items(
    segment_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsItemsResponse:
    rows = service.list_items(
        current=current,
        segment_id=segment_id,
        run_id=run_id,
        status="ranked",
        limit=limit,
        offset=offset,
    )
    return SocialNewsItemsResponse(items=[SocialNewsItemResponse(**row) for row in rows])


@router.get("/curation/stage2", response_model=SocialNewsItemsResponse)
def list_curation_stage2_items(
    segment_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsItemsResponse:
    rows = service.list_items(
        current=current,
        segment_id=segment_id,
        run_id=run_id,
        status="rewritten",
        limit=limit,
        offset=offset,
    )
    return SocialNewsItemsResponse(items=[SocialNewsItemResponse(**row) for row in rows])


@router.get("/curation/ready", response_model=SocialNewsItemsResponse)
def list_curation_ready_items(
    segment_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsItemsResponse:
    rows = service.list_items(
        current=current,
        segment_id=segment_id,
        run_id=run_id,
        status="approved_stage2",
        limit=limit,
        offset=offset,
    )
    return SocialNewsItemsResponse(items=[SocialNewsItemResponse(**row) for row in rows])


@router.get("/curation/dispatch-config", response_model=SocialNewsDispatchConfigResponse)
def get_curation_dispatch_config(
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsDispatchConfigResponse:
    service._assert_social_media_access(current)
    settings = get_settings()
    from_email = settings.email_from.strip()
    return SocialNewsDispatchConfigResponse(
        email_enabled=bool(settings.resend_api_key and from_email),
        from_email=from_email or None,
        resend_api_key_configured=bool(settings.resend_api_key),
    )


@router.post("/curation/items/{item_id}/stage1", response_model=SocialNewsItemResponse)
def decide_curation_stage1_item(
    item_id: str,
    data: SocialNewsStageDecisionRequest,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsItemResponse:
    if data.action == "reject":
        item = service.reject_stage1(
            current=current,
            item_id=item_id,
            rejection_reason=data.motivo,
        )
        return SocialNewsItemResponse(**item)

    item, _job = service.approve_stage1(
        current=current,
        item_id=item_id,
        idempotency_key=data.idempotency_key,
        rewrite_on_approve=data.rewrite_on_approve,
    )
    return SocialNewsItemResponse(**item)


@router.post("/curation/items/{item_id}/rewrite", response_model=SocialNewsItemResponse)
def rewrite_curation_item(
    item_id: str,
    data: SocialNewsJobRequest | None = None,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsItemResponse:
    service.enqueue_rewrite(
        current=current,
        item_id=item_id,
        idempotency_key=data.idempotency_key if data else None,
    )
    item = service.get_item(current=current, item_id=item_id)
    return SocialNewsItemResponse(**item)


@router.post("/curation/items/{item_id}/stage2", response_model=SocialNewsItemResponse)
def decide_curation_stage2_item(
    item_id: str,
    data: SocialNewsStageDecisionRequest,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsItemResponse:
    if data.action == "reject":
        item = service.reject_stage2(
            current=current,
            item_id=item_id,
            rejection_reason=data.motivo,
        )
        return SocialNewsItemResponse(**item)

    item = service.approve_stage2(current=current, item_id=item_id)
    return SocialNewsItemResponse(**item)


@router.post("/curation/runs/{run_id}/dispatch", response_model=SocialNewsDispatchEnqueuedResponse)
def dispatch_curation_run(
    run_id: str,
    data: SocialNewsJobRequest | None = None,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsDispatchEnqueuedResponse:
    job = service.enqueue_dispatch(
        current=current,
        run_id=run_id,
        idempotency_key=data.idempotency_key if data else None,
    )
    preview = service.dispatch_preview(current=current, run_id=run_id)
    return SocialNewsDispatchEnqueuedResponse(
        **preview,
        job=_job_response(job),
    )


@router.get("/curation/dispatches", response_model=SocialNewsDispatchesResponse)
def list_curation_dispatches(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsDispatchesResponse:
    rows = service.list_dispatches(current=current, run_id=run_id, limit=limit)
    return SocialNewsDispatchesResponse(
        dispatches=[SocialNewsDispatchResponse(**row) for row in rows]
    )


@router.post("/runs/{run_id}/dispatch", response_model=SocialNewsJobResponse)
def enqueue_dispatch(
    run_id: str,
    data: SocialNewsJobRequest,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsJobResponse:
    job = service.enqueue_dispatch(
        current=current,
        run_id=run_id,
        idempotency_key=data.idempotency_key,
    )
    return SocialNewsJobResponse(job=_job_response(job))


@router.post("/items/{item_id}/approve-stage1", response_model=SocialNewsCurationResponse)
def approve_stage1(
    item_id: str,
    data: SocialNewsCurationRequest | None = None,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsCurationResponse:
    item, job = service.approve_stage1(
        current=current,
        item_id=item_id,
        idempotency_key=data.idempotency_key if data else None,
    )
    return SocialNewsCurationResponse(
        item=SocialNewsItemResponse(**item),
        job=_job_response(job) if job else None,
    )


@router.post("/items/{item_id}/reject-stage1", response_model=SocialNewsCurationResponse)
def reject_stage1(
    item_id: str,
    data: SocialNewsCurationRequest | None = None,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsCurationResponse:
    item = service.reject_stage1(
        current=current,
        item_id=item_id,
        rejection_reason=data.rejection_reason if data else None,
    )
    return SocialNewsCurationResponse(item=SocialNewsItemResponse(**item))


@router.post("/items/{item_id}/approve-stage2", response_model=SocialNewsCurationResponse)
def approve_stage2(
    item_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsCurationResponse:
    item = service.approve_stage2(current=current, item_id=item_id)
    return SocialNewsCurationResponse(item=SocialNewsItemResponse(**item))


@router.post("/items/{item_id}/reject-stage2", response_model=SocialNewsCurationResponse)
def reject_stage2(
    item_id: str,
    data: SocialNewsCurationRequest | None = None,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsCurationResponse:
    item = service.reject_stage2(
        current=current,
        item_id=item_id,
        rejection_reason=data.rejection_reason if data else None,
    )
    return SocialNewsCurationResponse(item=SocialNewsItemResponse(**item))


@router.post("/items/{item_id}/rewrite", response_model=SocialNewsJobResponse)
def enqueue_rewrite(
    item_id: str,
    data: SocialNewsJobRequest,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsJobResponse:
    job = service.enqueue_rewrite(
        current=current,
        item_id=item_id,
        idempotency_key=data.idempotency_key,
    )
    return SocialNewsJobResponse(job=_job_response(job))


@router.get("/segments/{segment_id}/subscribers", response_model=SocialNewsSubscribersResponse)
def list_subscribers(
    segment_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSubscribersResponse:
    rows = service.list_subscribers(
        current=current,
        segment_id=segment_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return SocialNewsSubscribersResponse(
        subscribers=[SocialNewsSubscriberResponse(**row) for row in rows]
    )


@router.post(
    "/segments/{segment_id}/subscribers",
    response_model=SocialNewsSubscriberCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscriber(
    segment_id: str,
    data: SocialNewsSubscriberCreate,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSubscriberCreatedResponse:
    row = service.create_subscriber(
        current=current,
        segment_id=segment_id,
        email=str(data.email),
        name=data.name,
        origin=data.origin,
        consent_source=data.consent_source,
        metadata=data.metadata,
    )
    token = str(row.pop("unsubscribe_token"))
    return SocialNewsSubscriberCreatedResponse(
        subscriber=SocialNewsSubscriberResponse(**row),
        unsubscribe_token=token,
    )


@router.post("/unsubscribe/{token}", response_model=SocialNewsUnsubscribeResponse)
def unsubscribe(
    token: str,
    request: Request,
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsUnsubscribeResponse:
    row = service.unsubscribe_by_token(
        token=token,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return SocialNewsUnsubscribeResponse(status=row["status"], subscriber_id=row["id"])


def _job_response(job: JobRecord) -> EnqueuedJobResponse:
    return EnqueuedJobResponse(
        id=job.id,
        job_type=job.job_type,
        queue_name=job.queue_name,
        status=job.status,
        idempotency_key=job.idempotency_key,
    )
