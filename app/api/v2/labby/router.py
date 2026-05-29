from fastapi import APIRouter

from app.api.v2.labby import health

router = APIRouter()
router.include_router(health.router)

