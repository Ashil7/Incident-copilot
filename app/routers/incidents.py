"""Create, list, and retrieve incidents without exposing internal file paths."""

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Environment, Incident, IncidentStatus
from app.schemas import IncidentResponse
from app.services.uploads import save_upload

router = APIRouter(prefix="/api/v1/incidents", tags=["Incidents"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=IncidentResponse, status_code=201)
def create_incident(
    request: Request,
    session: DatabaseSession,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    log_file: Annotated[UploadFile, File()],
    service_name: Annotated[str | None, Form(max_length=200)] = None,
    environment: Annotated[Environment, Form()] = Environment.DEV,
) -> IncidentResponse:
    """Save one validated log and its metadata; analysis is a later milestone."""
    saved_path: Path | None = None
    committed = False
    try:
        title = title.strip()
        if not title:
            raise HTTPException(422, "Title must not be blank.")
        saved_path = save_upload(log_file, request.app.state.settings)
        incident = Incident(
            title=title,
            service_name=service_name.strip() or None if service_name else None,
            environment=environment,
            status=IncidentStatus.UPLOADED,
            original_filename=log_file.filename,
            stored_file_path=str(saved_path),
        )
        session.add(incident)
        session.flush()
        # Validate before commit, so a schema failure cannot leave an orphaned row.
        response = IncidentResponse.model_validate(incident)
        session.commit()
        committed = True
        return response
    except (OSError, SQLAlchemyError):
        raise HTTPException(503, "Unable to store incident. Please retry later.") from None
    finally:
        try:
            if not committed:
                try:
                    session.rollback()
                finally:
                    if saved_path is not None:
                        saved_path.unlink(missing_ok=True)
        finally:
            log_file.file.close()


@router.get("", response_model=list[IncidentResponse])
def list_incidents(
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Incident]:
    """Return newest incidents first with bounded pagination."""
    statement = (
        select(Incident)
        .order_by(Incident.created_at.desc(), Incident.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.scalars(statement))


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: UUID, session: DatabaseSession) -> Incident:
    incident = session.get(Incident, str(incident_id))
    if incident is None:
        raise HTTPException(404, "Incident not found.")
    return incident
