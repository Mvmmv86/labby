from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.sales.widget_service import PublicWidgetService
from app.schemas.sales import (
    WidgetConfigResponse,
    WidgetMessageRequest,
    WidgetMessageResponse,
    WidgetMessagesResponse,
)

router = APIRouter(prefix="/widget", tags=["widget"])


def get_public_widget_service(db: Session = Depends(get_db)) -> PublicWidgetService:
    return PublicWidgetService(db)


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


@router.get("/{widget_id}/loader.js")
def get_widget_loader(
    widget_id: str,
    request: Request,
    service: PublicWidgetService = Depends(get_public_widget_service),
) -> Response:
    js = service.loader_js(
        widget_id=widget_id,
        api_origin=str(request.base_url).rstrip("/"),
        origin=request.headers.get("origin"),
    )
    return Response(
        content=js,
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get("/{widget_id}/config", response_model=WidgetConfigResponse)
def get_widget_config(
    widget_id: str,
    request: Request,
    service: PublicWidgetService = Depends(get_public_widget_service),
) -> dict:
    return service.config(widget_id=widget_id, origin=request.headers.get("origin"))


@router.post("/{widget_id}/messages", response_model=WidgetMessageResponse)
def send_widget_message(
    widget_id: str,
    data: WidgetMessageRequest,
    request: Request,
    service: PublicWidgetService = Depends(get_public_widget_service),
) -> dict:
    return service.receive_message(
        widget_id=widget_id,
        visitor_id=data.visitor_id,
        visitor_name=data.visitor_name,
        message=data.message,
        client_message_id=data.client_message_id or data.idempotency_key,
        client_ip=_client_ip(request),
        origin=request.headers.get("origin"),
    )


@router.get("/{widget_id}/messages", response_model=WidgetMessagesResponse)
def get_widget_messages(
    widget_id: str,
    request: Request,
    visitor_id: str = Query(min_length=1, max_length=160),
    after: str | None = Query(default=None, max_length=180),
    service: PublicWidgetService = Depends(get_public_widget_service),
) -> dict:
    return service.list_messages(
        widget_id=widget_id,
        visitor_id=visitor_id,
        after=after,
        client_ip=_client_ip(request),
        origin=request.headers.get("origin"),
    )
