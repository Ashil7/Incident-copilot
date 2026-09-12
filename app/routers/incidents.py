"""Create, list, and retrieve incidents without exposing internal file paths."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.database import get_db
from app.models import Environment, Incident, IncidentStatus, User, UserRole
from app.schemas import IncidentResponse
from app.services.audit import record_event
from app.services.incident_files import add_file, discard_saved
from app.services.pipeline import run_analysis
from app.services.storage import get_storage

router = APIRouter(prefix="/api/v1/incidents", tags=["Incidents"])
DatabaseSession = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.post("", response_model=IncidentResponse, status_code=202)
def create_incident(
    request: Request,
    background_tasks: BackgroundTasks,
    session: DatabaseSession,
    user: CurrentUser,
    title: Annotated[str, Form(min_length=1, max_length=200)],
    log_file: Annotated[UploadFile | None, File()] = None,
    log_files: Annotated[list[UploadFile] | None, File()] = None,
    service_name: Annotated[str | None, Form(max_length=200)] = None,
    environment: Annotated[Environment, Form()] = Environment.DEV,
) -> IncidentResponse:
    """Persist one or several validated files, then analyze their combined events."""
    uploads = ([log_file] if log_file else []) + (log_files or [])
    settings = request.app.state.settings
    storage = get_storage(settings)
    saved = []
    committed = False
    try:
        title = title.strip()
        if not title or not uploads:
            raise HTTPException(422, "A title and at least one log file are required.")
        if len(uploads) > settings.max_files_per_incident:
            raise HTTPException(422, "Too many files for one incident.")
        incident = Incident(
            owner_user_id=user.id,
            title=title,
            service_name=service_name.strip() or None if service_name else None,
            environment=environment,
            status=IncidentStatus.UPLOADED,
            original_filename=uploads[0].filename,
        )
        session.add(incident)
        session.flush()
        for upload in uploads:
            row = add_file(session, incident, upload, settings, storage, saved)
            record_event(session, user.id, "file.uploaded", "log_file", row.id)
        response = IncidentResponse.model_validate(incident)
        record_event(session, user.id, "incident.created", "incident", incident.id)
        session.commit()
        committed = True
        background_tasks.add_task(
            run_analysis, incident.id, request.app.state.session_factory, settings
        )
        return response
    except (OSError, SQLAlchemyError):
        raise HTTPException(503, "Unable to store incident. Please retry later.") from None
    finally:
        try:
            if not committed:
                try:
                    session.rollback()
                finally:
                    discard_saved(storage, saved)
        finally:
            for upload in uploads:
                upload.file.close()


@router.get("", response_model=list[IncidentResponse])
def list_incidents(
    session: DatabaseSession,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    status: IncidentStatus | None = None,
    environment: Environment | None = None,
    service_name: Annotated[str | None, Query(max_length=200)] = None,
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    sort: Literal[
        "created_at", "-created_at", "title", "-title", "status", "-status"
    ] = "-created_at",
) -> list[Incident]:
    """Apply ownership before filters, ordering, and bounded pagination."""
    for value in (created_from, created_to):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(422, "Time filters must include a timezone.")
    if created_from and created_to and created_from > created_to:
        raise HTTPException(422, "created_from must not exceed created_to.")
    statement = select(Incident)
    if user.role != UserRole.ADMIN:
        statement = statement.where(Incident.owner_user_id == user.id)
    for column, value in (
        (Incident.status, status),
        (Incident.environment, environment),
        (Incident.service_name, service_name),
        (Incident.severity, severity),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if created_from:
        statement = statement.where(Incident.created_at >= created_from)
    if created_to:
        statement = statement.where(Incident.created_at <= created_to)
    column = {
        "created_at": Incident.created_at,
        "title": Incident.title,
        "status": Incident.status,
    }[sort.lstrip("-")]
    ordering = column.desc() if sort.startswith("-") else column.asc()
    statement = statement.order_by(ordering, Incident.id.asc()).offset(offset).limit(limit)
    return list(session.scalars(statement))


@router.get("/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: UUID, session: DatabaseSession, user: CurrentUser) -> Incident:
    statement = select(Incident).where(Incident.id == str(incident_id))
    if user.role != UserRole.ADMIN:
        statement = statement.where(Incident.owner_user_id == user.id)
    incident = session.scalar(statement)
    if incident is None:
        raise HTTPException(404, "Incident not found.")
    return incident
