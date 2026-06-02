from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, require_module
from app.domains.sales.conversation_service import SalesConversationService
from app.schemas.sales import (
    SalesConversationDetail,
    SalesConversationMarkReadResponse,
    SalesConversationMutationResponse,
    SalesConversationsResponse,
    SalesConversationUpdateRequest,
    SalesMessageCreateRequest,
    SalesMessageResponse,
    SalesMessagesResponse,
    SalesNotificationSummary,
)

router = APIRouter(tags=["sales-conversations"])
require_sales_module = require_module("sales")


def get_sales_conversation_service(
    db: Session = Depends(get_db),
) -> SalesConversationService:
    return SalesConversationService(db)


@router.get("/sales/conversations/", response_model=SalesConversationsResponse)
@router.get("/conversations/", response_model=SalesConversationsResponse)
def list_conversations(
    channel_tipo: str | None = Query(default=None),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    atendente_id: UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesConversationService = Depends(get_sales_conversation_service),
) -> dict:
    return service.list_conversations(
        current=current,
        channel_tipo=channel_tipo,
        status=status,
        search=search,
        atendente_id=str(atendente_id) if atendente_id else None,
        page=page,
        per_page=per_page,
    )


@router.get(
    "/sales/conversations/notifications/summary",
    response_model=SalesNotificationSummary,
)
@router.get(
    "/conversations/notifications/summary",
    response_model=SalesNotificationSummary,
)
def notification_summary(
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesConversationService = Depends(get_sales_conversation_service),
) -> dict:
    return service.notification_summary(current=current)


@router.get("/sales/conversations/{conversation_id}", response_model=SalesConversationDetail)
@router.get("/conversations/{conversation_id}", response_model=SalesConversationDetail)
def get_conversation(
    conversation_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesConversationService = Depends(get_sales_conversation_service),
) -> dict:
    return service.get_conversation(
        current=current,
        conversation_id=str(conversation_id),
    )


@router.put(
    "/sales/conversations/{conversation_id}",
    response_model=SalesConversationMutationResponse,
)
@router.put(
    "/conversations/{conversation_id}",
    response_model=SalesConversationMutationResponse,
)
def update_conversation(
    conversation_id: UUID,
    data: SalesConversationUpdateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesConversationService = Depends(get_sales_conversation_service),
) -> dict:
    return service.update_conversation(
        current=current,
        conversation_id=str(conversation_id),
        patch=data.model_dump(exclude_unset=True),
    )


@router.get(
    "/sales/conversations/{conversation_id}/messages",
    response_model=SalesMessagesResponse,
)
@router.get("/conversations/{conversation_id}/messages", response_model=SalesMessagesResponse)
def list_messages(
    conversation_id: UUID,
    cursor: UUID | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesConversationService = Depends(get_sales_conversation_service),
) -> dict:
    return service.list_messages(
        current=current,
        conversation_id=str(conversation_id),
        cursor=str(cursor) if cursor else None,
        limit=limit,
    )


@router.post(
    "/sales/conversations/{conversation_id}/mark-read",
    response_model=SalesConversationMarkReadResponse,
)
@router.post(
    "/conversations/{conversation_id}/mark-read",
    response_model=SalesConversationMarkReadResponse,
)
def mark_conversation_read(
    conversation_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesConversationService = Depends(get_sales_conversation_service),
) -> dict:
    return service.mark_read(current=current, conversation_id=str(conversation_id))


@router.post(
    "/sales/conversations/{conversation_id}/messages",
    response_model=SalesMessageResponse,
    status_code=201,
)
@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=SalesMessageResponse,
    status_code=201,
)
def send_message(
    conversation_id: UUID,
    data: SalesMessageCreateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesConversationService = Depends(get_sales_conversation_service),
) -> dict:
    return service.send_message(
        current=current,
        conversation_id=str(conversation_id),
        conteudo=data.conteudo,
        tipo=data.tipo,
    )


@router.post(
    "/sales/conversations/{conversation_id}/close",
    response_model=SalesConversationMutationResponse,
)
@router.post(
    "/conversations/{conversation_id}/close",
    response_model=SalesConversationMutationResponse,
)
def close_conversation(
    conversation_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesConversationService = Depends(get_sales_conversation_service),
) -> dict:
    return service.close_conversation(current=current, conversation_id=str(conversation_id))
