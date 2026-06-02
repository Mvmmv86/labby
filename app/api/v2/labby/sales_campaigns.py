from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, require_module
from app.domains.sales.campaign_service import SalesCampaignService
from app.schemas.sales import (
    SalesCampaignAddRecipientsResponse,
    SalesCampaignCreateRequest,
    SalesCampaignDeleteResponse,
    SalesCampaignDetail,
    SalesCampaignDispatchRequest,
    SalesCampaignDispatchResponse,
    SalesCampaignMutationResponse,
    SalesCampaignPreviewResponse,
    SalesCampaignRecipientsRequest,
    SalesCampaignRecipientsResponse,
    SalesCampaignsResponse,
    SalesCampaignUpdateRequest,
)

router = APIRouter(tags=["sales-campaigns"])
require_sales_module = require_module("sales")


def get_sales_campaign_service(db: Session = Depends(get_db)) -> SalesCampaignService:
    return SalesCampaignService(db)


@router.get("/sales/campaigns/", response_model=SalesCampaignsResponse)
@router.get("/campaigns/", response_model=SalesCampaignsResponse)
def list_campaigns(
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    return service.list_campaigns(
        current=current,
        status=status,
        page=page,
        per_page=per_page,
    )


@router.post("/sales/campaigns/", response_model=SalesCampaignMutationResponse, status_code=201)
@router.post("/campaigns/", response_model=SalesCampaignMutationResponse, status_code=201)
def create_campaign(
    data: SalesCampaignCreateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    contact_ids = data.contact_ids if data.contact_ids is not None else data.contatos_ids
    scheduled_at = data.scheduled_at if data.scheduled_at is not None else data.agendado_para
    return service.create_campaign(
        current=current,
        nome=data.nome,
        conteudo=data.conteudo,
        descricao=data.descricao,
        channel_id=str(data.channel_id) if data.channel_id else None,
        tipo_mensagem=data.tipo_mensagem,
        contact_ids=[str(contact_id) for contact_id in contact_ids or []],
        scheduled_at=scheduled_at,
        idempotency_key=data.idempotency_key,
    )


@router.get("/sales/campaigns/{campaign_id}", response_model=SalesCampaignDetail)
@router.get("/campaigns/{campaign_id}", response_model=SalesCampaignDetail)
def get_campaign(
    campaign_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    return service.get_campaign(current=current, campaign_id=str(campaign_id))


@router.put("/sales/campaigns/{campaign_id}", response_model=SalesCampaignMutationResponse)
@router.put("/campaigns/{campaign_id}", response_model=SalesCampaignMutationResponse)
def update_campaign(
    campaign_id: UUID,
    data: SalesCampaignUpdateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    patch = data.model_dump(exclude_unset=True)
    if "agendado_para" in patch and "scheduled_at" not in patch:
        patch["scheduled_at"] = patch.pop("agendado_para")
    else:
        patch.pop("agendado_para", None)
    return service.update_campaign(
        current=current,
        campaign_id=str(campaign_id),
        patch=patch,
    )


@router.delete("/sales/campaigns/{campaign_id}", response_model=SalesCampaignDeleteResponse)
@router.delete("/campaigns/{campaign_id}", response_model=SalesCampaignDeleteResponse)
def delete_campaign(
    campaign_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    return service.delete_campaign(current=current, campaign_id=str(campaign_id))


@router.get(
    "/sales/campaigns/{campaign_id}/recipients",
    response_model=SalesCampaignRecipientsResponse,
)
@router.get("/campaigns/{campaign_id}/recipients", response_model=SalesCampaignRecipientsResponse)
def list_campaign_recipients(
    campaign_id: UUID,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    return service.list_recipients(
        current=current,
        campaign_id=str(campaign_id),
        page=page,
        per_page=per_page,
    )


@router.post(
    "/sales/campaigns/{campaign_id}/recipients",
    response_model=SalesCampaignAddRecipientsResponse,
)
@router.post(
    "/campaigns/{campaign_id}/recipients",
    response_model=SalesCampaignAddRecipientsResponse,
)
def add_campaign_recipients(
    campaign_id: UUID,
    data: SalesCampaignRecipientsRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    return service.add_recipients(
        current=current,
        campaign_id=str(campaign_id),
        contact_ids=[str(contact_id) for contact_id in data.contact_ids],
    )


@router.post(
    "/sales/campaigns/{campaign_id}/preview-recipients",
    response_model=SalesCampaignPreviewResponse,
)
@router.post(
    "/campaigns/{campaign_id}/preview-recipients",
    response_model=SalesCampaignPreviewResponse,
)
def preview_campaign_recipients(
    campaign_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    return service.preview_recipients(current=current, campaign_id=str(campaign_id))


@router.post("/sales/campaigns/{campaign_id}/start", response_model=SalesCampaignMutationResponse)
@router.post("/campaigns/{campaign_id}/start", response_model=SalesCampaignMutationResponse)
def start_campaign(
    campaign_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    return service.start_campaign(current=current, campaign_id=str(campaign_id))


@router.post("/sales/campaigns/{campaign_id}/cancel", response_model=SalesCampaignMutationResponse)
@router.post("/campaigns/{campaign_id}/cancel", response_model=SalesCampaignMutationResponse)
def cancel_campaign(
    campaign_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    return service.cancel_campaign(current=current, campaign_id=str(campaign_id))


@router.post(
    "/sales/campaigns/{campaign_id}/dispatch",
    response_model=SalesCampaignDispatchResponse,
)
@router.post("/campaigns/{campaign_id}/dispatch", response_model=SalesCampaignDispatchResponse)
def dispatch_campaign(
    campaign_id: UUID,
    data: SalesCampaignDispatchRequest | None = None,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesCampaignService = Depends(get_sales_campaign_service),
) -> dict:
    data = data or SalesCampaignDispatchRequest()
    return service.dispatch_campaign(
        current=current,
        campaign_id=str(campaign_id),
        idempotency_key=data.idempotency_key,
    )
