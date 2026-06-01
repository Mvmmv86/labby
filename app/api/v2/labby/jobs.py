from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.jobs.job_service import JobQueueService
from app.schemas.jobs import JobMetricsResponse, JobQueueMetricResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])

ADMIN_ROLES = {"owner", "admin"}


def get_job_queue_service(db: Session = Depends(get_db)) -> JobQueueService:
    return JobQueueService(db)


@router.get("/metrics", response_model=JobMetricsResponse)
def queue_metrics(
    current: CurrentMembership = Depends(get_current_membership),
    service: JobQueueService = Depends(get_job_queue_service),
) -> JobMetricsResponse:
    if current.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Permissao insuficiente")

    metrics = service.queue_metrics(tenant_id=str(current.tenant_id))
    return JobMetricsResponse(
        metrics=[
            JobQueueMetricResponse(
                queue_name=metric.queue_name,
                status=metric.status,
                count=metric.count,
            )
            for metric in metrics
        ]
    )

