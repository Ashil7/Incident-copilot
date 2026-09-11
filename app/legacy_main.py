"""Preserved database entry point: run with uvicorn app.legacy_main:app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401 -- Register ORM tables before create_all.
from app.config import Settings
from app.database import Base, create_database_engine, create_session_factory
from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Create missing tables at startup and release connections on shutdown."""
    engine = create_database_engine(application.state.settings)
    try:
        Base.metadata.create_all(engine)
        application.state.session_factory = create_session_factory(engine)
        yield
    finally:
        engine.dispose()


def create_app() -> FastAPI:
    """Validate configuration and register application routes."""
    settings = Settings()
    application = FastAPI(
        title="AI Incident & Log Analysis Copilot",
        description="Day 2: PostgreSQL persistence and FastAPI foundation.",
        version="0.2.0",
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.include_router(health_router)
    return application


app = create_app()
