from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.access.module_service import ModuleService
from app.schemas.modules import (
    CurrentModulesResponse,
    UpdateUserModulesRequest,
    UpdateUserModulesResponse,
    UserModulesResponse,
)

router = APIRouter(prefix="/modules", tags=["modules"])


def get_module_service(db: Session = Depends(get_db)) -> ModuleService:
    return ModuleService(db)


@router.get("/", response_model=CurrentModulesResponse)
def current_modules(
    current: CurrentMembership = Depends(get_current_membership),
    service: ModuleService = Depends(get_module_service),
) -> CurrentModulesResponse:
    return service.current_modules(current)


@router.get("/users", response_model=UserModulesResponse)
def list_user_modules(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    current: CurrentMembership = Depends(get_current_membership),
    service: ModuleService = Depends(get_module_service),
) -> UserModulesResponse:
    return service.list_users(
        current=current,
        limit=limit,
        offset=offset,
        search=search,
    )


@router.patch("/users/{user_id}", response_model=UpdateUserModulesResponse)
def update_user_modules(
    user_id: str,
    data: UpdateUserModulesRequest,
    current: CurrentMembership = Depends(get_current_membership),
    service: ModuleService = Depends(get_module_service),
) -> UpdateUserModulesResponse:
    return service.update_user_modules(
        current=current,
        user_id=user_id,
        module_keys=data.module_keys,
        default_module=data.default_module,
        expected_updated_at=data.expected_updated_at,
    )
