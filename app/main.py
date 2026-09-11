"""Application entry point: run with uvicorn app.main:app."""

from fastapi import FastAPI

from app.config import Settings
from app.routers.health import router as health_router


def create_app() -> FastAPI:
    """Validate configuration and register the Day 1 routes."""
    settings = Settings()
    application = FastAPI(
        title="AI Incident & Log Analysis Copilot",
        description="Day 1: FastAPI foundation and application health.",
        version="0.1.0",
    )
    application.state.settings = settings
    application.include_router(health_router)
    return application


app = create_app()
