from pydantic import BaseModel


class JobQueueMetricResponse(BaseModel):
    queue_name: str
    status: str
    count: int


class JobMetricsResponse(BaseModel):
    metrics: list[JobQueueMetricResponse]

