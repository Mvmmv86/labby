from fastapi import APIRouter

from app.api.v2.labby import (
    auth,
    health,
    jobs,
    modules,
    sales_contacts,
    sales_conversations,
    social_news,
    team,
)

router = APIRouter()
router.include_router(auth.router)
router.include_router(health.router)
router.include_router(jobs.router)
router.include_router(modules.router)
router.include_router(sales_contacts.router)
router.include_router(sales_conversations.router)
router.include_router(social_news.router)
router.include_router(team.router)
