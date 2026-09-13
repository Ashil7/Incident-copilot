"""Filtered incident events and authenticated RCA PDF downloads."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.database import get_db
from app.models import LogEvent, User
from app.services.incident_files import owned_incident
from app.services.reports import incident_pdf
from app.services.similar_incidents import similar_incidents

router = APIRouter(prefix="/api/v1/incidents", tags=["Incident reports"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("/{incident_id}/events")
def events(
    incident_id: UUID,
    session: Database,
    user: CurrentUser,
    level: str | None = None,
    status_code: int | None = None,
    endpoint: Annotated[str | None, Query(max_length=200)] = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    evidence_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    incident = owned_incident(session, incident_id, user)
    for value in (created_from, created_to):
        if value is not None and value.utcoffset() is None:
            raise HTTPException(422, "Time filters must include a timezone.")
    query = select(LogEvent).where(LogEvent.incident_id == incident.id)
    for column, value in ((LogEvent.level, level), (LogEvent.status_code, status_code)):
        if value is not None:
            query = query.where(column == value)
    if endpoint:
        query = query.where(LogEvent.endpoint.contains(endpoint, autoescape=True))
    if created_from:
        query = query.where(LogEvent.timestamp >= created_from)
    if created_to:
        query = query.where(LogEvent.timestamp <= created_to)
    if evidence_only:
        query = query.where(LogEvent.is_evidence.is_(True))
    return [
        {
            "id": row.id,
            "source_file_id": row.log_file_id,
            "line_number": row.source_line_number,
            "timestamp": row.timestamp,
            "level": row.level,
            "endpoint": row.endpoint,
            "status_code": row.status_code,
            "latency_ms": row.latency_ms,
            "message": row.redacted_message,
            "is_evidence": row.is_evidence,
        }
        for row in session.scalars(query.order_by(LogEvent.source_line_number).limit(limit))
    ]


@router.get("/{incident_id}/report.pdf")
def report(incident_id: UUID, request: Request, session: Database, user: CurrentUser):
    incident = owned_incident(session, incident_id, user)
    return Response(
        incident_pdf(
            incident,
            [
                item
                for item in similar_incidents(session, incident, request.app.state.settings)
                if item[1].resolution_notes
            ],
        ),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="incident-{incident.id}.pdf"'},
    )
