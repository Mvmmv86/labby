from fastapi import APIRouter

from app.api.v2.labby import (
    auth,
    health,
    jobs,
    modules,
    sales_analytics,
    sales_campaigns,
    sales_channels,
    sales_contacts,
    sales_conversations,
    sales_webhooks,
    social_news,
    team,
)

router = APIRouter()
router.include_router(auth.router)
router.include_router(health.router)
router.include_router(jobs.router)
router.include_router(modules.router)
router.include_router(sales_analytics.router)
router.include_router(sales_campaigns.router)
router.include_router(sales_channels.router)
router.include_router(sales_contacts.router)
router.include_router(sales_conversations.router)
router.include_router(sales_webhooks.router)
router.include_router(social_news.router)
router.include_router(team.router)
