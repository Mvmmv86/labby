from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, require_module
from app.domains.sales.bot_service import SalesBotService
from app.schemas.sales import (
    SalesBotCreateRequest,
    SalesBotDeleteResponse,
    SalesBotDetail,
    SalesBotsResponse,
    SalesBotToggleResponse,
    SalesBotUpdateRequest,
)

router = APIRouter(tags=["sales-bots"])
require_sales_module = require_module("sales")


def get_sales_bot_service(db: Session = Depends(get_db)) -> SalesBotService:
    return SalesBotService(db)


@router.get("/sales/bots/", response_model=SalesBotsResponse)
@router.get("/bots/", response_model=SalesBotsResponse)
def list_bots(
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesBotService = Depends(get_sales_bot_service),
) -> dict:
    return service.list_bots(
        current=current,
        search=search,
        page=page,
        per_page=per_page,
    )


@router.post("/sales/bots/", response_model=SalesBotDetail, status_code=201)
@router.post("/bots/", response_model=SalesBotDetail, status_code=201)
def create_bot(
    data: SalesBotCreateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesBotService = Depends(get_sales_bot_service),
) -> dict:
    return service.create_bot(
        current=current,
        nome=data.nome,
        descricao=data.descricao,
        system_prompt=data.system_prompt,
        welcome_message=data.welcome_message,
        fallback_message=data.fallback_message,
        base_conhecimento=data.base_conhecimento,
        faqs=data.faqs,
        modelo=data.modelo,
        temperatura=data.temperatura,
        max_tokens=data.max_tokens,
        tipo_trigger=data.tipo_trigger,
        trigger_valor=data.trigger_valor,
        channel_ids=[str(channel_id) for channel_id in data.channel_ids or []],
    )


@router.get("/sales/bots/{bot_id}", response_model=SalesBotDetail)
@router.get("/bots/{bot_id}", response_model=SalesBotDetail)
def get_bot(
    bot_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesBotService = Depends(get_sales_bot_service),
) -> dict:
    return service.get_bot(current=current, bot_id=str(bot_id))


@router.put("/sales/bots/{bot_id}", response_model=SalesBotDetail)
@router.put("/bots/{bot_id}", response_model=SalesBotDetail)
def update_bot(
    bot_id: UUID,
    data: SalesBotUpdateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesBotService = Depends(get_sales_bot_service),
) -> dict:
    return service.update_bot(
        current=current,
        bot_id=str(bot_id),
        patch=data.model_dump(exclude_unset=True),
    )


@router.delete("/sales/bots/{bot_id}", response_model=SalesBotDeleteResponse)
@router.delete("/bots/{bot_id}", response_model=SalesBotDeleteResponse)
def delete_bot(
    bot_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesBotService = Depends(get_sales_bot_service),
) -> dict:
    return service.delete_bot(current=current, bot_id=str(bot_id))


@router.post("/sales/bots/{bot_id}/toggle", response_model=SalesBotToggleResponse)
@router.post("/bots/{bot_id}/toggle", response_model=SalesBotToggleResponse)
def toggle_bot(
    bot_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesBotService = Depends(get_sales_bot_service),
) -> dict:
    return service.toggle_bot(current=current, bot_id=str(bot_id))


@router.post("/sales/bots/{bot_id}/duplicate", response_model=SalesBotDetail, status_code=201)
@router.post("/bots/{bot_id}/duplicate", response_model=SalesBotDetail, status_code=201)
def duplicate_bot(
    bot_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesBotService = Depends(get_sales_bot_service),
) -> dict:
    return service.duplicate_bot(current=current, bot_id=str(bot_id))
