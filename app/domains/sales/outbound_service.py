from app.domains.jobs.job_service import JobQueueService, JobRecord

SALES_MESSAGE_DISPATCH_JOB = "sales.message.dispatch"
SALES_OUTBOUND_QUEUE = "worker-sales-outbound"


def sales_message_dispatch_idempotency_key(message_id: str) -> str:
    return f"sales.message.dispatch:{message_id}:v1"


def enqueue_sales_message_dispatch(
    *,
    job_queue: JobQueueService,
    tenant_id: str,
    message_id: str,
    membership_id: str | None = None,
    commit: bool = True,
) -> JobRecord:
    return job_queue.enqueue_job(
        tenant_id=tenant_id,
        membership_id=membership_id,
        job_type=SALES_MESSAGE_DISPATCH_JOB,
        queue_name=SALES_OUTBOUND_QUEUE,
        idempotency_key=sales_message_dispatch_idempotency_key(message_id),
        payload={"message_id": message_id},
        max_attempts=3,
        commit=commit,
    )
