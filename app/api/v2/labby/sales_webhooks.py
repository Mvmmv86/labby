from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.sales.webhook_service import SalesWebhookReceiver
from app.schemas.sales import SalesWebhookReceiveResponse

router = APIRouter(tags=["sales-webhooks"])


def get_sales_webhook_receiver(db: Session = Depends(get_db)) -> SalesWebhookReceiver:
    return SalesWebhookReceiver(db)


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        forwarded_chain = [part.strip() for part in forwarded_for.split(",") if part.strip()]
        if forwarded_chain:
            return forwarded_chain[-1]
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


@router.post("/webhooks/evolution/{channel_id}", response_model=SalesWebhookReceiveResponse)
async def evolution_webhook(
    channel_id: UUID,
    request: Request,
    receiver: SalesWebhookReceiver = Depends(get_sales_webhook_receiver),
) -> dict:
    payload = await request.json()
    if not isinstance(payload, dict):
        payload = {"raw": payload}
    return receiver.receive_evolution(
        channel_id=str(channel_id),
        payload=payload,
        headers={key.lower(): value for key, value in request.headers.items()},
        client_ip=_client_ip(request),
    )
