from fastapi import APIRouter

from app.api.v2.labby import auth, health

router = APIRouter()
router.include_router(auth.router)
router.include_router(health.router)
