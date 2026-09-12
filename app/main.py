"""Application entry point: run with uvicorn app.main:app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app import models  # noqa: F401 -- Register tables in Base.metadata before create_all.
from app.config import Settings
from app.database import Base, create_database_engine, create_session_factory
from app.routers.health import router as health_router
from app.routers.incidents import router as incident_router


def create_app(
    settings: Settings | None = None, *, database_engine: Engine | None = None
) -> FastAPI:
    """Validate configuration and register application routes."""
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine = database_engine
        try:
            try:
                if engine is None:
                    engine = create_database_engine(settings)
                Base.metadata.create_all(engine)
            except SQLAlchemyError:
                raise RuntimeError(
                    "Database startup failed. Check PostgreSQL availability and configuration."
                ) from None
            application.state.session_factory = create_session_factory(engine)
            yield
        finally:
            if engine is not None:
                engine.dispose()

    application = FastAPI(
        title=settings.app_name,
        description="Phase 1, Milestone 1.3: secure log uploads and incident APIs.",
        version="0.3.0",
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = settings
    application.include_router(health_router)
    application.include_router(incident_router)
    return application


app = create_app()
