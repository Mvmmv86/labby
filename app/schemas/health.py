from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
    environment: str


class DependencyHealth(BaseModel):
    ok: bool
    error: str | None = None


class ReadinessResponse(HealthResponse):
    dependencies: dict[str, DependencyHealth]
