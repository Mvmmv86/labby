from fastapi import APIRouter, Response, status

from app.core.config import get_settings
from app.core.health import readiness_status
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        service="labby-backend",
        environment=settings.environment,
    )


@router.get("/healthz", response_model=ReadinessResponse)
def readiness(response: Response) -> ReadinessResponse:
    settings = get_settings()
    ok, dependencies = readiness_status()
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ok" if ok else "degraded",
        service="labby-backend",
        environment=settings.environment,
        dependencies={
            name: dependency.as_dict()
            for name, dependency in dependencies.items()
        },
    )
