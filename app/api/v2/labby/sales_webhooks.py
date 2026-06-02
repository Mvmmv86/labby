from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.sales.webhook_service import SalesWebhookReceiver
from app.schemas.sales import SalesWebhookReceiveResponse

router = APIRouter(tags=["sales-webhooks"])


def get_sales_webhook_receiver(db: Session = Depends(get_db)) -> SalesWebhookReceiver:
    return SalesWebhookReceiver(db)


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
    )
