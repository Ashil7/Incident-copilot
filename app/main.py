"""Application entry point: run with uvicorn app.main:app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException

from app.config import PROJECT_ROOT, Settings
from app.database import create_database_engine, create_session_factory
from app.errors import ErrorResponse, http_error_handler, validation_error_handler
from app.migration_state import verify_schema
from app.observability import configure_logging
from app.request_context import RequestContextMiddleware
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.feedback import router as feedback_router
from app.routers.files import router as file_router
from app.routers.health import router as health_router
from app.routers.incidents import router as incident_router
from app.routers.jobs import router as job_router
from app.routers.reports import router as report_router
from app.routers.runbooks import router as runbook_router
from app.routers.web import router as web_router
from app.task_queue import TaskQueue


def create_app(
    settings: Settings | None = None, *, database_engine: Engine | None = None
) -> FastAPI:
    """Validate configuration and register application routes."""
    settings = settings if settings is not None else Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging()
        engine = database_engine
        queue = None
        try:
            try:
                if engine is None:
                    engine = create_database_engine(settings)
                with engine.connect() as connection:
                    verify_schema(connection)
            except SQLAlchemyError:
                raise RuntimeError(
                    "Database startup failed. Check PostgreSQL availability and configuration."
                ) from None
            application.state.session_factory = create_session_factory(engine)
            settings.validate_auth_configuration()
            settings.validate_storage_configuration()
            queue = TaskQueue(settings)
            application.state.task_queue = queue
            yield
        finally:
            if queue is not None:
                queue.close()
            if engine is not None:
                engine.dispose()

    application = FastAPI(
        title=settings.app_name,
        description="Phase 5: incident dashboard, retrieval UI, and RCA reports.",
        version="0.23.0",
        responses={
            status: {"model": ErrorResponse}
            for status in (400, 401, 403, 404, 405, 409, 413, 422, 429, 500, 503)
        },
        debug=settings.debug,
        lifespan=lifespan,
    )
    application.state.settings = settings

    application.add_exception_handler(HTTPException, http_error_handler)
    application.add_exception_handler(RequestValidationError, validation_error_handler)
    application.add_middleware(RequestContextMiddleware)

    application.include_router(auth_router)
    application.include_router(admin_router)
    application.include_router(health_router)
    application.include_router(incident_router)
    application.include_router(file_router)
    application.include_router(job_router)
    application.include_router(runbook_router)
    application.include_router(feedback_router)
    application.include_router(report_router)
    application.include_router(web_router)
    application.mount(
        "/static", StaticFiles(directory=PROJECT_ROOT / "app" / "static"), name="static"
    )
    return application


app = create_app()
