"""Ownership-protected job progress and explicit analysis/retry requests."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.database import get_db
from app.models import AnalysisJob, IncidentAnalysis, IncidentStatus, User
from app.services.audit import record_event
from app.services.incident_files import adopt_legacy, file_rows, owned_incident, reset_analysis
from app.services.jobs import new_job
from app.services.storage import get_storage
from app.task_queue import enqueue_processing

router = APIRouter(prefix="/api/v1/incidents/{incident_id}", tags=["Analysis jobs"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    incident_id: str
    status: str
    progress: int
    current_stage: str | None
    attempt_count: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    retry_at: datetime | None


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    incident_id: str
    prompt_version: str | None
    provider: str
    model: str | None
    result: dict
    input_tokens: int | None
    output_tokens: int | None
    duration_seconds: float | None
    created_at: datetime


def latest(session, incident_id):
    return session.scalar(
        select(AnalysisJob)
        .where(AnalysisJob.incident_id == incident_id)
        .order_by(AnalysisJob.created_at.desc(), AnalysisJob.id.desc())
        .limit(1)
    )


@router.get("/jobs/latest", response_model=JobResponse)
def latest_job(incident_id: UUID, session: Database, user: CurrentUser):
    incident = owned_incident(session, incident_id, user)
    job = latest(session, incident.id)
    if job is None:
        raise HTTPException(404, "Analysis job not found.")
    return job


@router.get("/analysis", response_model=AnalysisResponse)
def latest_analysis(incident_id: UUID, session: Database, user: CurrentUser):
    incident = owned_incident(session, incident_id, user)
    analysis = session.scalar(
        select(IncidentAnalysis)
        .where(IncidentAnalysis.incident_id == incident.id)
        .order_by(IncidentAnalysis.created_at.desc(), IncidentAnalysis.id.desc())
        .limit(1)
    )
    if analysis is None:
        raise HTTPException(404, "Analysis not found.")
    return analysis


def schedule(incident_id, request, session, user, *, retry):
    try:
        incident = owned_incident(session, incident_id, user, lock=True)
        previous = latest(session, incident.id)
        if retry and (
            incident.status != IncidentStatus.FAILED or (previous and previous.status != "FAILED")
        ):
            raise HTTPException(409, "Only a failed analysis may be retried.")
        settings = request.app.state.settings
        adopt_legacy(session, incident, settings)
        rows = file_rows(session, incident.id)
        if not rows:
            raise HTTPException(409, "Upload a log file before requesting analysis.")
        if any(row.storage_scope != get_storage(settings).scope for row in rows):
            raise HTTPException(409, "Files belong to another storage environment.")
        reset_analysis(incident, True)
        job = new_job(session, incident)
        response = JobResponse.model_validate(job)
        record_event(
            session,
            user.id,
            "analysis.retry_requested" if retry else "analysis.requested",
            "incident",
            incident.id,
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            409, "Files cannot change while analysis is queued or running."
        ) from None
    enqueue_processing(request, incident.id, job_id=job.id)
    return response


@router.post("/analysis", response_model=JobResponse, status_code=202)
def request_analysis(incident_id: UUID, request: Request, session: Database, user: CurrentUser):
    return schedule(incident_id, request, session, user, retry=False)


@router.post("/analysis/retry", response_model=JobResponse, status_code=202)
def retry_analysis(incident_id: UUID, request: Request, session: Database, user: CurrentUser):
    return schedule(incident_id, request, session, user, retry=True)
