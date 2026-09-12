"""Application liveness endpoint."""

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import DomainError
from app.migration_state import verify_schema
from app.services.storage import get_storage

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/health", response_model=HealthResponse)
@router.get("/health/live", response_model=HealthResponse)
def health() -> HealthResponse:
    """Confirm that the API is running; external services are not checked."""
    return HealthResponse()


@router.get("/health/ready", response_model=HealthResponse)
def readiness(request: Request, session: Session = Depends(get_db)) -> HealthResponse:
    """Verify schema/connectivity and local read/write access; no provider call."""
    try:
        verify_schema(session.connection())
    except SQLAlchemyError:
        raise DomainError("DATABASE_UNAVAILABLE") from None
    except RuntimeError:
        raise DomainError("SCHEMA_NOT_READY") from None
    try:
        get_storage(request.app.state.settings).check_ready()
    except (OSError, ValueError):
        raise DomainError("STORAGE_UNAVAILABLE") from None
    return HealthResponse()
