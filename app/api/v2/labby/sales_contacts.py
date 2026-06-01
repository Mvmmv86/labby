from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, require_module
from app.domains.sales.contact_service import SalesContactService
from app.schemas.sales import (
    SalesContactBatchRequest,
    SalesContactBatchResponse,
    SalesContactCreateRequest,
    SalesContactDeleteResponse,
    SalesContactDetail,
    SalesContactMutationResponse,
    SalesContactsResponse,
    SalesContactUpdateRequest,
)

router = APIRouter(tags=["sales-contacts"])
require_sales_module = require_module("sales")


def get_sales_contact_service(db: Session = Depends(get_db)) -> SalesContactService:
    return SalesContactService(db)


@router.get("/sales/contacts/", response_model=SalesContactsResponse)
@router.get("/contacts/", response_model=SalesContactsResponse)
def list_contacts(
    search: str | None = Query(default=None),
    grupo: str | None = Query(default=None),
    tag: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesContactService = Depends(get_sales_contact_service),
) -> dict:
    return service.list_contacts(
        current=current,
        search=search,
        grupo=grupo,
        tag=tag,
        page=page,
        per_page=per_page,
    )


@router.post("/sales/contacts/", response_model=SalesContactMutationResponse, status_code=201)
@router.post("/contacts/", response_model=SalesContactMutationResponse, status_code=201)
def create_contact(
    data: SalesContactCreateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesContactService = Depends(get_sales_contact_service),
) -> dict:
    return service.create_contact(
        current=current,
        nome=data.nome,
        telefone=data.telefone,
        email=str(data.email) if data.email else None,
        grupo=data.grupo,
        tags=data.tags,
        notas=data.notas,
        campos_custom=data.campos_custom,
    )


@router.post("/sales/contacts/batch", response_model=SalesContactBatchResponse)
@router.post("/contacts/batch", response_model=SalesContactBatchResponse)
def batch_import_contacts(
    data: SalesContactBatchRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesContactService = Depends(get_sales_contact_service),
) -> dict:
    return service.batch_import_contacts(
        current=current,
        contacts=data.contacts,
        on_duplicate=data.on_duplicate,
    )


@router.get("/sales/contacts/{contact_id}", response_model=SalesContactDetail)
@router.get("/contacts/{contact_id}", response_model=SalesContactDetail)
def get_contact(
    contact_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesContactService = Depends(get_sales_contact_service),
) -> dict:
    return service.get_contact(current=current, contact_id=str(contact_id))


@router.put("/sales/contacts/{contact_id}", response_model=SalesContactMutationResponse)
@router.put("/contacts/{contact_id}", response_model=SalesContactMutationResponse)
def update_contact(
    contact_id: UUID,
    data: SalesContactUpdateRequest,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesContactService = Depends(get_sales_contact_service),
) -> dict:
    return service.update_contact(
        current=current,
        contact_id=str(contact_id),
        patch=data.model_dump(exclude_unset=True),
    )


@router.delete("/sales/contacts/{contact_id}", response_model=SalesContactDeleteResponse)
@router.delete("/contacts/{contact_id}", response_model=SalesContactDeleteResponse)
def delete_contact(
    contact_id: UUID,
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesContactService = Depends(get_sales_contact_service),
) -> dict:
    return service.delete_contact(current=current, contact_id=str(contact_id))
