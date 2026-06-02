from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import CurrentMembership, require_module
from app.domains.sales.analytics_service import SalesAnalyticsService
from app.schemas.sales import (
    SalesDashboardStats,
    SalesMessageVolumeResponse,
    SalesRecentActivityItem,
)

router = APIRouter(tags=["sales-analytics"])
require_sales_module = require_module("sales")


def get_sales_analytics_service(db: Session = Depends(get_db)) -> SalesAnalyticsService:
    return SalesAnalyticsService(db)


@router.get("/sales/analytics/dashboard", response_model=SalesDashboardStats)
@router.get("/analytics/dashboard", response_model=SalesDashboardStats)
def dashboard(
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesAnalyticsService = Depends(get_sales_analytics_service),
) -> dict:
    return service.dashboard(current=current)


@router.get("/sales/analytics/messages", response_model=SalesMessageVolumeResponse)
@router.get("/analytics/messages", response_model=SalesMessageVolumeResponse)
def message_volume(
    period: str = Query(default="7d", pattern="^(7d|30d|90d)$"),
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesAnalyticsService = Depends(get_sales_analytics_service),
) -> dict:
    return service.message_volume(current=current, period=period)


@router.get("/sales/analytics/activity", response_model=list[SalesRecentActivityItem])
@router.get("/analytics/activity", response_model=list[SalesRecentActivityItem])
def recent_activity(
    limit: int = Query(default=10, ge=1, le=30),
    current: CurrentMembership = Depends(require_sales_module),
    service: SalesAnalyticsService = Depends(get_sales_analytics_service),
) -> list[dict]:
    return service.recent_activity(current=current, limit=limit)
