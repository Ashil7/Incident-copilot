"""Ownership-protected file sets; edits serialize against pipeline claims."""

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.database import get_db
from app.models import LogEvent, StorageDeletion, User
from app.schemas import LogFileResponse
from app.services.audit import record_event
from app.services.incident_files import (
    add_file,
    adopt_legacy,
    discard_saved,
    file_rows,
    owned_incident,
    reset_analysis,
)
from app.services.jobs import new_job
from app.services.storage import get_storage
from app.task_queue import enqueue_processing

router = APIRouter(prefix="/api/v1/incidents/{incident_id}/files", tags=["Incident files"])
Database = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]


@router.get("", response_model=list[LogFileResponse])
def list_files(incident_id: UUID, session: Database, user: CurrentUser):
    incident = owned_incident(session, incident_id, user)
    return file_rows(session, incident.id)


@router.post("", response_model=list[LogFileResponse], status_code=202)
def attach_files(
    incident_id: UUID,
    request: Request,
    session: Database,
    user: CurrentUser,
    log_files: Annotated[list[UploadFile], File()],
):
    settings = request.app.state.settings
    storage, saved, committed = get_storage(settings), [], False
    try:
        incident = owned_incident(session, incident_id, user, lock=True)
        adopt_legacy(session, incident, settings)
        existing = file_rows(session, incident.id)
        if any(row.storage_scope != storage.scope for row in existing):
            raise HTTPException(409, "Files belong to another storage environment.")
        if not log_files or len(existing) + len(log_files) > settings.max_files_per_incident:
            raise HTTPException(422, "File count exceeds the incident limit.")
        added = []
        for upload in log_files:
            row = add_file(session, incident, upload, settings, storage, saved)
            record_event(session, user.id, "file.uploaded", "log_file", row.id)
            added.append(LogFileResponse.model_validate(row))
        reset_analysis(incident, True)
        if not existing:
            incident.original_filename = log_files[0].filename
        job = new_job(session, incident)
        session.commit()
        committed = True
        enqueue_processing(request, incident.id, job_id=job.id)
        return added
    except (OSError, SQLAlchemyError):
        raise HTTPException(503, "Unable to attach files.") from None
    finally:
        try:
            if not committed:
                try:
                    session.rollback()
                finally:
                    discard_saved(storage, saved)
        finally:
            for upload in log_files:
                upload.file.close()


@router.delete("/{file_id}", status_code=204)
def delete_file(
    incident_id: UUID,
    file_id: UUID,
    request: Request,
    session: Database,
    user: CurrentUser,
):
    try:
        incident = owned_incident(session, incident_id, user, lock=True)
        rows = file_rows(session, incident.id)
        target = next((row for row in rows if row.id == str(file_id)), None)
        if target is None:
            raise HTTPException(404, "File not found.")
        scope = get_storage(request.app.state.settings).scope
        if any(row.storage_scope != scope for row in rows):
            raise HTTPException(409, "Files belong to another storage environment.")
        remaining = [row for row in rows if row.id != target.id]
        session.execute(delete(LogEvent).where(LogEvent.log_file_id == target.id))
        session.add(StorageDeletion(storage_key=target.storage_key, storage_scope=scope))
        session.delete(target)
        reset_analysis(incident, bool(remaining))
        incident.original_filename = remaining[0].original_filename if remaining else None
        record_event(session, user.id, "file.deleted", "log_file", target.id)
        job = new_job(session, incident, analyze=bool(remaining), cleanup=True)
        session.commit()
        enqueue_processing(
            request, incident.id, analyze=bool(remaining), cleanup=True, job_id=job.id
        )
        return Response(status_code=204)
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Unable to delete file.") from None
