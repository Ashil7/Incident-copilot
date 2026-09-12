"""Application liveness endpoint."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Confirm that the API is running; external services are not checked."""
    return HealthResponse()


@router.get("/health/ready", response_model=HealthResponse)
def readiness(session: Session = Depends(get_db)) -> HealthResponse:
    """Check that the database accepts a query without exposing connection details."""
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable.") from None
    return HealthResponse()
