"""Application entry point: run with uvicorn app.main:app."""

from fastapi import FastAPI

from app.config import Settings
from app.routers.health import router as health_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Validate configuration and register application routes."""
    settings = settings if settings is not None else Settings()
    application = FastAPI(
        title=settings.app_name,
        description="Phase 1, Milestone 1.1: application foundation.",
        version="0.1.0",
        debug=settings.debug,
    )
    application.state.settings = settings
    application.include_router(health_router)
    return application


app = create_app()
