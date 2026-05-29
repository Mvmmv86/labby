from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v2.labby.router import router as labby_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    docs_url = "/docs" if settings.docs_enabled else None
    redoc_url = "/redoc" if settings.docs_enabled else None
    openapi_url = "/openapi.json" if settings.docs_enabled else None

    app = FastAPI(
        title="Labby API",
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    @app.get("/health", tags=["health"])
    def root_health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "labby-backend",
            "environment": settings.environment,
        }

    app.include_router(labby_router, prefix="/api/v2/labby")
    return app


app = create_app()

