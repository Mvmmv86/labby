import csv
import io

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
    SocialNewsCuratorMutationResponse,
    SocialNewsCuratorUpsertRequest,
    SocialNewsDispatchConfigResponse,
    SocialNewsFrontendCuratorResponse,
    SocialNewsFrontendDispatchesResponse,
    SocialNewsFrontendDispatchResponse,
    SocialNewsFrontendDispatchRunResponse,
    SocialNewsFrontendItemResponse,
    SocialNewsFrontendItemsResponse,
    SocialNewsFrontendRunResponse,
    SocialNewsFrontendRunsResponse,
    SocialNewsFrontendScheduleResponse,
    SocialNewsFrontendSchedulesResponse,
    SocialNewsFrontendSegmentResponse,
    SocialNewsFrontendSegmentsResponse,
    SocialNewsFrontendSourceResponse,
    SocialNewsFrontendSourcesResponse,
    SocialNewsFrontendSubscriberCreate,
    SocialNewsFrontendSubscriberPatch,
    SocialNewsFrontendSubscriberResponse,
    SocialNewsFrontendSubscribersResponse,
    SocialNewsItemResponse,
    SocialNewsItemsResponse,
    SocialNewsJobRequest,
    SocialNewsJobResponse,
    SocialNewsManualRunCreate,
    SocialNewsManualRunResponse,
    SocialNewsRunCreate,
    SocialNewsRunCreatedResponse,
    SocialNewsRunResponse,
    SocialNewsSchedulePatch,
    SocialNewsScheduleRecalibrationResponse,
    SocialNewsSegmentCreate,
    SocialNewsSegmentFromSeedCreate,
    SocialNewsSegmentMutationResponse,
    SocialNewsSegmentPatch,
    SocialNewsSourceCreate,
    SocialNewsSourceMutationResponse,
    SocialNewsStageDecisionRequest,
    SocialNewsSubscriberCreate,
    SocialNewsSubscriberCreatedResponse,
    SocialNewsSubscriberCsvImportRequest,
    SocialNewsSubscriberCsvImportResponse,
    SocialNewsSubscriberResponse,
    SocialNewsSubscribersResponse,
    SocialNewsUnsubscribeResponse,
)

router = APIRouter(prefix="/social/news", tags=["social-news"])

FRONTEND_ITEM_STATUS = {
    "captured": "capturado",
    "ranked": "ranqueado",
    "discarded_rank": "descartado_rank",
    "approved_stage1": "aprovado_stage1",
    "rejected_stage1": "rejeitado_stage1",
    "rewritten": "reescrito",
    "approved_stage2": "aprovado_stage2",
    "rejected_stage2": "rejeitado_stage2",
    "sent": "enviado",
}

FRONTEND_RANKING_SOURCE = {
    "engagement": "top_engagement",
    "top_engagement": "top_engagement",
    "exploration": "exploracao",
    "exploracao": "exploracao",
}

FRONTEND_RUN_STATUS = {
    "queued": "capturando",
    "capturing": "capturando",
    "curation_stage1": "curadoria_stage1",
    "rewriting": "reescrevendo",
    "curation_stage2": "curadoria_stage2",
    "sending": "enviando",
    "succeeded": "concluida",
    "failed": "erro",
    "cancelled": "cancelada",
}
BACKEND_RUN_STATUS = {value: key for key, value in FRONTEND_RUN_STATUS.items()}
BACKEND_ITEM_STATUS = {value: key for key, value in FRONTEND_ITEM_STATUS.items()}


def get_social_news_service(db: Session = Depends(get_db)) -> SocialNewsService:
    return SocialNewsService(db, job_queue=JobQueueService(db))


@router.get("/segments", response_model=SocialNewsFrontendSegmentsResponse)
def list_segments(
    status_filter: str | None = Query(default=None, alias="status"),
    active_filter: bool | None = Query(default=None, alias="ativo"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendSegmentsResponse:
    rows = service.list_segments(
        current=current,
        status=status_filter,
        active=active_filter,
        limit=limit,
        offset=offset,
    )
    return SocialNewsFrontendSegmentsResponse(segments=[_frontend_segment(row) for row in rows])


@router.post(
    "/segments",
    response_model=SocialNewsSegmentMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_segment(
    data: SocialNewsSegmentCreate,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSegmentMutationResponse:
    name = data.name or data.nome
    config = {"idioma": data.idioma, **data.config}
    row = service.create_segment(
        current=current,
        slug=data.slug,
        name=name or data.slug,
        description=data.description if data.description is not None else data.descricao,
        base_knowledge=(
            data.base_knowledge if data.base_knowledge is not None else data.base_conhecimento
        ),
        disclaimer=data.disclaimer,
        min_engagement_score=data.min_engagement_score,
        config=config,
    )
    return SocialNewsSegmentMutationResponse(id=row["id"], slug=row["slug"])


@router.post(
    "/segments/from-seed",
    response_model=SocialNewsSegmentMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_segment_from_seed(
    data: SocialNewsSegmentFromSeedCreate,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSegmentMutationResponse:
    row = service.create_segment_from_seed(current=current, seed_origem=data.seed_origem)
    config = row.get("config") or {}
    return SocialNewsSegmentMutationResponse(
        id=row["id"],
        slug=row["slug"],
        seed_origem=str(config.get("seed_origem") or data.seed_origem),
    )


@router.get("/segments/{segment_id}", response_model=SocialNewsFrontendSegmentResponse)
def get_segment(
    segment_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendSegmentResponse:
    row = service.get_segment(current=current, segment_id=segment_id)
    return _frontend_segment(row)


@router.patch("/segments/{segment_id}", response_model=SocialNewsSegmentMutationResponse)
def update_segment(
    segment_id: str,
    data: SocialNewsSegmentPatch,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSegmentMutationResponse:
    row = service.update_segment(
        current=current,
        segment_id=segment_id,
        patch=data.model_dump(exclude_unset=True),
    )
    return SocialNewsSegmentMutationResponse(id=row["id"], updated=True)


@router.delete("/segments/{segment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_segment(
    segment_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> None:
    service.delete_segment(current=current, segment_id=segment_id)


@router.get("/segments/{segment_id}/sources", response_model=SocialNewsFrontendSourcesResponse)
def list_sources(
    segment_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendSourcesResponse:
    rows = service.list_sources(current=current, segment_id=segment_id)
    return SocialNewsFrontendSourcesResponse(sources=[_frontend_source(row) for row in rows])


@router.post(
    "/segments/{segment_id}/sources",
    response_model=SocialNewsSourceMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_source(
    segment_id: str,
    data: SocialNewsSourceCreate,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSourceMutationResponse:
    value = data.value or data.valor
    row = service.add_source(
        current=current,
        segment_id=segment_id,
        source_type=data.source_type,
        value=value or "",
        provider=data.provider,
        min_likes=data.min_likes,
        min_reposts=data.min_reposts,
        min_replies=data.min_replies,
        min_impressions=data.min_impressions,
        metadata=data.metadata,
    )
    return SocialNewsSourceMutationResponse(id=row["id"])


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(
    source_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> None:
    service.delete_source(current=current, source_id=source_id)


@router.get("/segments/{segment_id}/curator", response_model=SocialNewsFrontendCuratorResponse)
def get_curator(
    segment_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendCuratorResponse:
    row = service.get_curator(current=current, segment_id=segment_id)
    return _frontend_curator(row)


@router.put("/segments/{segment_id}/curator", response_model=SocialNewsCuratorMutationResponse)
def upsert_curator(
    segment_id: str,
    data: SocialNewsCuratorUpsertRequest,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsCuratorMutationResponse:
    row = service.upsert_curator(
        current=current,
        segment_id=segment_id,
        name=data.nome,
        model=data.modelo,
        temperature=data.temperatura,
        max_tokens=data.max_tokens,
        system_prompt=data.system_prompt_complementar,
        base_knowledge=data.base_conhecimento,
        active=data.ativo,
    )
    return SocialNewsCuratorMutationResponse(id=row["id"], segment_id=row["segment_id"])


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


@router.post(
    "/runs/manual",
    response_model=SocialNewsManualRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_manual_run(
    data: SocialNewsManualRunCreate,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsManualRunResponse:
    run, _job = service.start_run(
        current=current,
        segment_id=str(data.segment_id),
        run_type="manual",
    )
    return SocialNewsManualRunResponse(
        id=run["id"],
        status=FRONTEND_RUN_STATUS.get(str(run["status"]), str(run["status"])),
    )


@router.get("/runs", response_model=SocialNewsFrontendRunsResponse)
def list_runs(
    segment_id: str | None = Query(default=None),
    run_type: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendRunsResponse:
    rows = service.list_runs(
        current=current,
        segment_id=segment_id,
        run_type=_backend_run_type(run_type),
        status=_backend_run_status(status_filter),
        limit=limit,
        offset=offset,
    )
    return SocialNewsFrontendRunsResponse(runs=[_frontend_run(row) for row in rows])


@router.get("/runs/{run_id}", response_model=SocialNewsFrontendRunResponse)
def get_run(
    run_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendRunResponse:
    row = service.get_run(current=current, run_id=run_id)
    return _frontend_run(row)


@router.get("/runs/{run_id}/items", response_model=SocialNewsFrontendItemsResponse)
def list_run_items(
    run_id: str,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendItemsResponse:
    rows = service.list_run_items(
        current=current,
        run_id=run_id,
        status=BACKEND_ITEM_STATUS.get(status_filter, status_filter),
        limit=limit,
    )
    return SocialNewsFrontendItemsResponse(items=[_frontend_item(row) for row in rows])


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


@router.get(
    "/segments/{segment_id}/schedules",
    response_model=SocialNewsFrontendSchedulesResponse,
)
def list_segment_schedules(
    segment_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendSchedulesResponse:
    rows = service.list_schedules(current=current, segment_id=segment_id)
    return SocialNewsFrontendSchedulesResponse(schedules=[_frontend_schedule(row) for row in rows])


@router.post(
    "/segments/{segment_id}/schedules/recalibrate",
    response_model=SocialNewsScheduleRecalibrationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def recalibrate_segment_schedules(
    segment_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsScheduleRecalibrationResponse:
    run, rows = service.recalibrate_schedules(current=current, segment_id=segment_id)
    return SocialNewsScheduleRecalibrationResponse(
        run_id=run["id"],
        schedules=[_frontend_schedule(row) for row in rows],
    )


@router.patch("/schedules/{schedule_id}", response_model=SocialNewsFrontendScheduleResponse)
def update_schedule(
    schedule_id: str,
    data: SocialNewsSchedulePatch,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendScheduleResponse:
    row = service.update_schedule(
        current=current,
        schedule_id=schedule_id,
        patch=data.model_dump(exclude_unset=True),
    )
    return _frontend_schedule(row)


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_schedule(
    schedule_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> None:
    service.delete_schedule(current=current, schedule_id=schedule_id)


@router.get("/curation/stage1", response_model=SocialNewsFrontendItemsResponse)
def list_curation_stage1_items(
    segment_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendItemsResponse:
    rows = service.list_items(
        current=current,
        segment_id=segment_id,
        run_id=run_id,
        status="ranked",
        limit=limit,
        offset=offset,
    )
    return SocialNewsFrontendItemsResponse(items=[_frontend_item(row) for row in rows])


@router.get("/curation/stage2", response_model=SocialNewsFrontendItemsResponse)
def list_curation_stage2_items(
    segment_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendItemsResponse:
    rows = service.list_items(
        current=current,
        segment_id=segment_id,
        run_id=run_id,
        status="rewritten",
        limit=limit,
        offset=offset,
    )
    return SocialNewsFrontendItemsResponse(items=[_frontend_item(row) for row in rows])


@router.get("/curation/ready", response_model=SocialNewsFrontendItemsResponse)
def list_curation_ready_items(
    segment_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendItemsResponse:
    rows = service.list_items(
        current=current,
        segment_id=segment_id,
        run_id=run_id,
        status="approved_stage2",
        limit=limit,
        offset=offset,
    )
    return SocialNewsFrontendItemsResponse(items=[_frontend_item(row) for row in rows])


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


@router.post("/curation/items/{item_id}/stage1", response_model=SocialNewsFrontendItemResponse)
def decide_curation_stage1_item(
    item_id: str,
    data: SocialNewsStageDecisionRequest,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendItemResponse:
    if data.action == "reject":
        item = service.reject_stage1(
            current=current,
            item_id=item_id,
            rejection_reason=data.motivo,
        )
        return _frontend_item(item)

    item, _job = service.approve_stage1(
        current=current,
        item_id=item_id,
        idempotency_key=data.idempotency_key,
        rewrite_on_approve=data.rewrite_on_approve,
    )
    return _frontend_item(item)


@router.post("/curation/items/{item_id}/rewrite", response_model=SocialNewsFrontendItemResponse)
def rewrite_curation_item(
    item_id: str,
    data: SocialNewsJobRequest | None = None,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendItemResponse:
    service.enqueue_rewrite(
        current=current,
        item_id=item_id,
        idempotency_key=data.idempotency_key if data else None,
    )
    item = service.get_item(current=current, item_id=item_id)
    return _frontend_item(item)


@router.post("/curation/items/{item_id}/stage2", response_model=SocialNewsFrontendItemResponse)
def decide_curation_stage2_item(
    item_id: str,
    data: SocialNewsStageDecisionRequest,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendItemResponse:
    if data.action == "reject":
        item = service.reject_stage2(
            current=current,
            item_id=item_id,
            rejection_reason=data.motivo,
        )
        return _frontend_item(item)

    item = service.approve_stage2(current=current, item_id=item_id)
    return _frontend_item(item)


@router.post(
    "/curation/runs/{run_id}/dispatch",
    response_model=SocialNewsFrontendDispatchRunResponse,
)
def dispatch_curation_run(
    run_id: str,
    data: SocialNewsJobRequest | None = None,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendDispatchRunResponse:
    service.enqueue_dispatch(
        current=current,
        run_id=run_id,
        idempotency_key=data.idempotency_key if data else None,
    )
    preview = service.dispatch_preview(current=current, run_id=run_id)
    return SocialNewsFrontendDispatchRunResponse(**preview)


@router.get("/curation/dispatches", response_model=SocialNewsFrontendDispatchesResponse)
def list_curation_dispatches(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendDispatchesResponse:
    rows = service.list_dispatches(current=current, run_id=run_id, limit=limit)
    return SocialNewsFrontendDispatchesResponse(
        dispatches=[_frontend_dispatch(row) for row in rows]
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


@router.get("/subscribers", response_model=SocialNewsFrontendSubscribersResponse)
def list_flat_subscribers(
    segment_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendSubscribersResponse:
    rows = service.list_subscribers(
        current=current,
        segment_id=segment_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return SocialNewsFrontendSubscribersResponse(
        subscribers=[_frontend_subscriber(row) for row in rows]
    )


@router.post(
    "/subscribers",
    response_model=SocialNewsFrontendSubscriberResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_flat_subscriber(
    data: SocialNewsFrontendSubscriberCreate,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendSubscriberResponse:
    row = service.create_subscriber(
        current=current,
        segment_id=str(data.segment_id),
        email=str(data.email),
        name=data.nome,
        origin=data.origem,
        consent_source="admin",
    )
    row.pop("unsubscribe_token", None)
    return _frontend_subscriber(row)


@router.post("/subscribers/import-csv", response_model=SocialNewsSubscriberCsvImportResponse)
def import_subscribers_csv(
    data: SocialNewsSubscriberCsvImportRequest,
    request: Request,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsSubscriberCsvImportResponse:
    reader = csv.DictReader(io.StringIO(data.csv_text))
    created = 0
    skipped = 0
    errors: list[str] = []
    for line_number, row in enumerate(reader, start=2):
        email = (row.get("email") or row.get("Email") or "").strip()
        name = (row.get("nome") or row.get("name") or row.get("Nome") or "").strip() or None
        if not email:
            skipped += 1
            continue
        try:
            created_row = service.create_subscriber(
                current=current,
                segment_id=str(data.segment_id),
                email=email,
                name=name,
                origin="csv",
                consent_source="csv_import",
                metadata={
                    "csv_line": line_number,
                    "ip": request.client.host if request.client else None,
                },
            )
            created_row.pop("unsubscribe_token", None)
            created += 1
        except Exception as exc:  # noqa: BLE001 - keep import best-effort and report rows.
            message = str(getattr(exc, "detail", exc))
            if "ja existe" in message.lower():
                skipped += 1
            else:
                errors.append(f"linha {line_number}: {message}")
    return SocialNewsSubscriberCsvImportResponse(
        created=created,
        skipped=skipped,
        errors=errors[:20],
    )


@router.patch("/subscribers/{subscriber_id}", response_model=SocialNewsFrontendSubscriberResponse)
def update_flat_subscriber(
    subscriber_id: str,
    data: SocialNewsFrontendSubscriberPatch,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsFrontendSubscriberResponse:
    row = service.update_subscriber(
        current=current,
        subscriber_id=subscriber_id,
        patch=data.model_dump(exclude_unset=True),
    )
    return _frontend_subscriber(row)


@router.delete("/subscribers/{subscriber_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_flat_subscriber(
    subscriber_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: SocialNewsService = Depends(get_social_news_service),
) -> None:
    service.delete_subscriber(current=current, subscriber_id=subscriber_id)


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
    return SocialNewsUnsubscribeResponse(
        status=row["status"],
        subscriber_id=row["id"],
        email=row["email_normalized"],
        segment_id=row["segment_id"],
    )


@router.get("/unsubscribe/{token}", response_model=SocialNewsUnsubscribeResponse)
def get_unsubscribe_status(
    token: str,
    service: SocialNewsService = Depends(get_social_news_service),
) -> SocialNewsUnsubscribeResponse:
    row = service.resolve_unsubscribe_token(token)
    return SocialNewsUnsubscribeResponse(
        status=row["status"],
        subscriber_id=row["id"],
        email=row["email_normalized"],
        segment_id=row["segment_id"],
    )


def _frontend_segment(row) -> SocialNewsFrontendSegmentResponse:
    config = _json_dict(row.get("config"))
    return SocialNewsFrontendSegmentResponse(
        id=row["id"],
        slug=row["slug"],
        nome=row["name"],
        idioma=str(config.get("idioma") or "pt"),
        descricao=row.get("description"),
        disclaimer=row.get("disclaimer"),
        base_conhecimento=row.get("base_knowledge"),
        min_engagement_score=int(row.get("min_engagement_score") or 0),
        tipos_evento=list(config.get("tipos_evento") or []),
        vocabulario=list(config.get("vocabulario") or []),
        ativo=row.get("status") == "active",
        created_at=row["created_at"],
    )


def _frontend_source(row) -> SocialNewsFrontendSourceResponse:
    metadata = _json_dict(row.get("metadata_json"))
    return SocialNewsFrontendSourceResponse(
        id=row["id"],
        source_type=row["source_type"],
        valor=row["value"],
        min_likes=int(row.get("min_likes") or 0),
        min_reposts=int(row.get("min_reposts") or 0),
        min_replies=int(row.get("min_replies") or 0),
        min_impressions=int(row.get("min_impressions") or 0),
        ativo=row.get("status") == "active",
        origem=str(metadata.get("origem") or metadata.get("origin") or "user"),
        created_at=row["created_at"],
    )


def _frontend_curator(row) -> SocialNewsFrontendCuratorResponse:
    return SocialNewsFrontendCuratorResponse(
        id=row["id"],
        segment_id=row["segment_id"],
        nome=row["name"],
        modelo=row["model"],
        temperatura=float(row.get("temperature") or 0),
        max_tokens=int(row.get("max_tokens") or 0),
        system_prompt_complementar=row.get("system_prompt"),
        base_conhecimento=row.get("base_knowledge"),
        ativo=row.get("status") == "active",
    )


def _frontend_run(row) -> SocialNewsFrontendRunResponse:
    return SocialNewsFrontendRunResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        segment_id=row["segment_id"],
        run_type=_frontend_run_type(row.get("run_type")),
        schedule_id=row.get("schedule_id"),
        window_start_at=row.get("window_start_at"),
        status=FRONTEND_RUN_STATUS.get(str(row.get("status")), str(row.get("status"))),
        candidatos_count=int(row.get("candidates_count") or 0),
        ranqueados_count=int(row.get("ranked_count") or 0),
        aprovados_stage1=int(row.get("approved_stage1_count") or 0),
        aprovados_stage2=int(row.get("approved_stage2_count") or 0),
        enviados_count=int(row.get("sent_count") or 0),
        falhas_count=int(row.get("failed_count") or 0),
        erro_mensagem=row.get("error_message"),
        iniciado_at=row.get("started_at") or row["created_at"],
        concluido_at=row.get("finished_at"),
        updated_at=row["updated_at"],
        iniciado_por=_optional_str(row.get("membership_id")),
        custo_estimado_usd=float(row.get("estimated_cost_usd") or 0),
        custo_x_api_usd=float(row.get("x_api_cost_usd") or 0),
        custo_llm_usd=float(row.get("ai_cost_usd") or 0),
        custo_resend_usd=float(row.get("email_cost_usd") or 0),
    )


def _frontend_schedule(row) -> SocialNewsFrontendScheduleResponse:
    return SocialNewsFrontendScheduleResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        segment_id=row["segment_id"],
        nome=row.get("name"),
        timezone=row.get("timezone") or "America/Sao_Paulo",
        day_of_week=row.get("day_of_week"),
        window_start_hour=int(row.get("window_start_hour") or 0),
        window_end_hour=int(row.get("window_end_hour") or 0),
        scheduled_hour=int(row.get("scheduled_hour") or 0),
        scheduled_minute=int(row.get("scheduled_minute") or 0),
        confidence_score=float(row.get("confidence_score") or 0),
        amostras_count=int(row.get("samples_count") or 0),
        score_medio=float(row["average_score"]) if row.get("average_score") is not None else None,
        descoberto_por=row.get("discovered_by") or "user",
        origem_run_id=row.get("origin_run_id"),
        ativo=row.get("status") == "active",
        last_run_at=row.get("last_run_at"),
        next_run_at=row.get("next_run_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _frontend_subscriber(row) -> SocialNewsFrontendSubscriberResponse:
    return SocialNewsFrontendSubscriberResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        segment_id=row["segment_id"],
        email=row["email_normalized"],
        nome=row.get("name"),
        status=row["status"],
        origem=row.get("origin") or "manual",
        consent_status=row.get("consent_status") or "unknown",
        consent_given_at=row.get("consent_given_at"),
        consent_source=row.get("consent_source"),
        unsubscribed_at=row.get("unsubscribed_at"),
        metadata=_json_dict(row.get("metadata_json")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _job_response(job: JobRecord) -> EnqueuedJobResponse:
    return EnqueuedJobResponse(
        id=job.id,
        job_type=job.job_type,
        queue_name=job.queue_name,
        status=job.status,
        idempotency_key=job.idempotency_key,
    )


def _frontend_item(row) -> SocialNewsFrontendItemResponse:
    author_metadata = row.get("author_metadata") or {}
    if not isinstance(author_metadata, dict):
        author_metadata = {}
    ranking_source = row.get("ranking_source")
    return SocialNewsFrontendItemResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        run_id=row["run_id"],
        segment_id=row["segment_id"],
        source_id=row.get("source_id"),
        source_type=row.get("source_type"),
        source_valor=row.get("source_valor") or row.get("source_value"),
        external_id=row["external_id"],
        external_url=row.get("external_url") or "",
        published_at=row.get("published_at"),
        autor_handle=row.get("author_handle") or "",
        autor_nome=row.get("author_name"),
        autor_verified=bool(
            author_metadata.get("verified") or author_metadata.get("is_blue_verified")
        ),
        autor_followers_count=author_metadata.get("followers_count")
        or author_metadata.get("followers"),
        conteudo_original=row["original_content"],
        media_urls=row.get("media_urls") or [],
        metrics=row.get("metrics") or {},
        ranking_score=row.get("ranking_score"),
        ranking_motivo=row.get("ranking_reason"),
        ranking_origem=FRONTEND_RANKING_SOURCE.get(str(ranking_source), ranking_source),
        tipo_match=row.get("type_match"),
        conteudo_reescrito=row.get("rewritten_content"),
        reescrito_modelo=row.get("rewritten_model"),
        reescrito_at=row.get("rewritten_at"),
        rejeitado_motivo=row.get("rejection_reason"),
        aprovado_stage1_por=_optional_str(row.get("approved_stage1_by_membership_id")),
        aprovado_stage1_at=row.get("approved_stage1_at"),
        aprovado_stage2_por=_optional_str(row.get("approved_stage2_by_membership_id")),
        aprovado_stage2_at=row.get("approved_stage2_at"),
        feedback_label=row.get("feedback_label"),
        status=FRONTEND_ITEM_STATUS.get(str(row.get("status")), str(row.get("status"))),
        created_at=row["created_at"],
    )


def _frontend_dispatch(row) -> SocialNewsFrontendDispatchResponse:
    return SocialNewsFrontendDispatchResponse(
        id=row["id"],
        tenant_id=row["tenant_id"],
        run_id=row["run_id"],
        subscriber_id=row["subscriber_id"],
        email=row.get("email") or row["email_normalized"],
        subject=row["subject"],
        status=row["status"],
        idempotency_key=row["idempotency_key"],
        resend_id=row.get("resend_id") or row.get("provider_message_id"),
        error_message=row.get("error_message"),
        sent_at=row.get("sent_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _optional_str(value) -> str | None:
    return str(value) if value is not None else None


def _json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    return {}


def _frontend_run_type(value) -> str:
    return "calibration" if value == "calibration" else "dispatch"


def _backend_run_type(value: str | None) -> str | None:
    if value == "dispatch":
        return None
    return value


def _backend_run_status(value: str | None) -> str | None:
    if value == "capturando":
        return "capturando"
    return BACKEND_RUN_STATUS.get(value, value)
