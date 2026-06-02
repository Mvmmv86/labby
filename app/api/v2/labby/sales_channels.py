from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, require_module
from app.domains.sales.channel_service import SalesChannelService
from app.schemas.sales import (
    SalesChannelConnectionResponse,
    SalesChannelConnectRequest,
    SalesChannelCreateRequest,
    SalesChannelDeleteResponse,
    SalesChannelResponse,
    SalesChannelsResponse,
    SalesChannelStatusResponse,
    SalesChannelUpdateRequest,
)

router = APIRouter(tags=["sales-channels"])
require_sales_module = require_module("sales")


def get_sales_channel_service(db: Session = Depends(get_db)) -> SalesChannelService:
    return SalesChannelService(db)


@router.get("/sales/channels/", response_model=SalesChannelsResponse)
@router.get("/channels/", response_model=SalesChannelsResponse)
def list_channels(
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesChannelService = Depends(get_sales_channel_service),
) -> dict:
    return service.list_channels(current=current)


@router.post("/sales/channels/", response_model=SalesChannelResponse, status_code=201)
@router.post("/channels/", response_model=SalesChannelResponse, status_code=201)
def create_channel(
    data: SalesChannelCreateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesChannelService = Depends(get_sales_channel_service),
) -> dict:
    return service.create_channel(
        current=current,
        tipo=data.tipo,
        nome=data.nome,
        config=data.config,
    )


@router.get("/sales/channels/{channel_id}", response_model=SalesChannelResponse)
@router.get("/channels/{channel_id}", response_model=SalesChannelResponse)
def get_channel(
    channel_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesChannelService = Depends(get_sales_channel_service),
) -> dict:
    return service.get_channel(current=current, channel_id=str(channel_id))


@router.put("/sales/channels/{channel_id}", response_model=SalesChannelResponse)
@router.put("/channels/{channel_id}", response_model=SalesChannelResponse)
def update_channel(
    channel_id: UUID,
    data: SalesChannelUpdateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesChannelService = Depends(get_sales_channel_service),
) -> dict:
    return service.update_channel(
        current=current,
        channel_id=str(channel_id),
        patch=data.model_dump(exclude_unset=True),
    )


@router.delete("/sales/channels/{channel_id}", response_model=SalesChannelDeleteResponse)
@router.delete("/channels/{channel_id}", response_model=SalesChannelDeleteResponse)
def delete_channel(
    channel_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesChannelService = Depends(get_sales_channel_service),
) -> dict:
    return service.delete_channel(current=current, channel_id=str(channel_id))


@router.get("/sales/channels/{channel_id}/status", response_model=SalesChannelStatusResponse)
@router.get("/channels/{channel_id}/status", response_model=SalesChannelStatusResponse)
def channel_status(
    channel_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesChannelService = Depends(get_sales_channel_service),
) -> dict:
    return service.channel_status(current=current, channel_id=str(channel_id))


@router.post(
    "/sales/channels/{channel_id}/connect",
    response_model=SalesChannelConnectionResponse,
)
@router.post(
    "/channels/{channel_id}/connect",
    response_model=SalesChannelConnectionResponse,
)
async def connect_channel(
    channel_id: UUID,
    data: SalesChannelConnectRequest | None = None,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesChannelService = Depends(get_sales_channel_service),
) -> dict:
    return await service.connect_channel(
        current=current,
        channel_id=str(channel_id),
        data=data.model_dump(exclude_unset=True) if data else {},
    )


@router.post(
    "/sales/channels/{channel_id}/disconnect",
    response_model=SalesChannelConnectionResponse,
)
@router.post(
    "/channels/{channel_id}/disconnect",
    response_model=SalesChannelConnectionResponse,
)
def disconnect_channel(
    channel_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesChannelService = Depends(get_sales_channel_service),
) -> dict:
    return service.disconnect_channel(current=current, channel_id=str(channel_id))
