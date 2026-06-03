from datetime import datetime

from pydantic import BaseModel, Field


class JobQueueMetricResponse(BaseModel):
    queue_name: str
    status: str
    count: int


class SalesOutboundStuckMetricResponse(BaseModel):
    status: str
    count: int
    oldest_created_at: datetime | None = None


class JobMetricsResponse(BaseModel):
    metrics: list[JobQueueMetricResponse]
    sales_outbound_stuck: list[SalesOutboundStuckMetricResponse] = Field(default_factory=list)
