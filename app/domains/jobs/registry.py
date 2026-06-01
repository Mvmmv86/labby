from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JobExecutionContext:
    job_id: str
    tenant_id: str
    membership_id: str | None
    job_type: str
    queue_name: str
    payload: dict[str, Any]
    attempts: int


JobHandler = Callable[[JobExecutionContext], Mapping[str, Any] | None]


class RetryableJobError(Exception):
    pass


class PermanentJobError(Exception):
    pass


class JobHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, JobHandler] = {}

    def register(self, job_type: str):
        def decorator(handler: JobHandler) -> JobHandler:
            self._handlers[job_type] = handler
            return handler

        return decorator

    def get(self, job_type: str) -> JobHandler | None:
        return self._handlers.get(job_type)


job_handlers = JobHandlerRegistry()

