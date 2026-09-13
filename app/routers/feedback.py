"""Human resolution, feedback, and owner-scoped similar-incident endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.database import get_db
from app.models import Feedback, User
from app.retrieval_schemas import (
    FeedbackCreate,
    FeedbackResponse,
    ResolutionUpdate,
    SimilarIncidentResponse,
)
from app.schemas import IncidentResponse
from app.services.audit import record_event
from app.services.incident_files import owned_incident
from app.services.similar_incidents import index_incident, similar_incidents, similarity_label

router = APIRouter(prefix="/api/v1/incidents", tags=["Incident retrieval"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.patch("/{incident_id}/resolution", response_model=IncidentResponse)
def update_resolution(
    incident_id: UUID,
    body: ResolutionUpdate,
    request: Request,
    session: Database,
    user: CurrentUser,
):
    incident = owned_incident(session, incident_id, user)
    incident.confirmed_root_cause = body.confirmed_root_cause.strip()
    incident.resolution_notes = body.resolution_notes.strip()
    if body.severity:
        incident.severity = body.severity
    record_event(session, user.id, "incident.resolution_updated", "incident", incident.id)
    session.commit()
    session.refresh(incident)
    try:
        index_incident(session, incident, request.app.state.settings)
    except Exception:
        session.rollback()  # The committed human resolution remains durable.
    return incident


@router.post("/{incident_id}/feedback", response_model=FeedbackResponse, status_code=201)
def create_feedback(incident_id: UUID, body: FeedbackCreate, session: Database, user: CurrentUser):
    incident = owned_incident(session, incident_id, user)
    row = Feedback(incident_id=incident.id, user_id=user.id, **body.model_dump())
    session.add(row)
    session.flush()
    record_event(session, user.id, "incident.feedback_created", "feedback", row.id)
    session.commit()
    session.refresh(row)
    return row


@router.get("/{incident_id}/similar", response_model=list[SimilarIncidentResponse])
def get_similar_incidents(
    incident_id: UUID, request: Request, session: Database, user: CurrentUser
):
    incident = owned_incident(session, incident_id, user)
    return [
        SimilarIncidentResponse(
            incident_id=other.id,
            title=other.title,
            similarity=similarity_label(score),
            confirmed_resolution=other.resolution_notes,
            incident_type=((other.analysis or {}).get("result") or {}).get("incident_type"),
        )
        for score, other in similar_incidents(session, incident, request.app.state.settings)
    ]
