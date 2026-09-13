"""File metadata, legacy adoption, and retriable post-commit object deletion."""

import hashlib
import logging
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select

from app.models import AnalysisJob, Incident, IncidentStatus, LogFile, StorageDeletion, UserRole
from app.services.storage import get_storage
from app.services.uploads import CHUNK_SIZE, store_upload

logger = logging.getLogger(__name__)
EDITABLE = {IncidentStatus.CREATED, IncidentStatus.COMPLETED, IncidentStatus.FAILED}


def owned_incident(session, incident_id, user, lock=False):
    query = select(Incident).where(Incident.id == str(incident_id))
    if user.role != UserRole.ADMIN:
        query = query.where(Incident.owner_user_id == user.id)
    if lock:
        query = query.with_for_update()
    incident = session.scalar(query)
    if incident is None:
        raise HTTPException(404, "Incident not found.")
    if lock and incident.status not in EDITABLE:
        raise HTTPException(409, "Files cannot change while analysis is queued or running.")
    if lock and session.scalar(
        select(AnalysisJob.id).where(
            AnalysisJob.incident_id == incident.id,
            AnalysisJob.status.in_(("PENDING", "RUNNING", "RETRY")),
        )
    ):
        raise HTTPException(409, "Files cannot change while analysis is queued or running.")
    return incident


def file_rows(session, incident_id):
    return list(
        session.scalars(
            select(LogFile)
            .where(LogFile.incident_id == incident_id)
            .order_by(LogFile.uploaded_at, LogFile.id)
        )
    )


def add_file(session, incident, upload, settings, storage, saved):
    item = store_upload(upload, settings, storage)
    saved.append(item.key)
    row = LogFile(
        incident_id=incident.id,
        original_filename=upload.filename,
        storage_key=item.key,
        storage_scope=storage.scope,
        mime_type=(upload.content_type or "").split(";", 1)[0].strip().lower(),
        size_bytes=item.size,
        sha256=item.sha256,
    )
    session.add(row)
    session.flush()
    return row


def adopt_legacy(session, incident, settings):
    if file_rows(session, incident.id) or not incident.stored_file_path:
        return
    storage = get_storage(settings)
    path = Path(incident.stored_file_path)
    try:
        if path.resolve() != storage.path(path.name).resolve():
            raise ValueError("Legacy path is unavailable in this environment.")
        digest, size = hashlib.sha256(), 0
        with storage.open(path.name) as source:
            while chunk := source.read(CHUNK_SIZE):
                size += len(chunk)
                if size > settings.max_upload_size_mb * 1024 * 1024:
                    raise ValueError("Legacy file exceeds limit.")
                digest.update(chunk)
        if not size:
            raise ValueError("Empty legacy file.")
    except (OSError, ValueError):
        raise HTTPException(
            409,
            "Legacy upload is unavailable in this storage environment; preserve the record and use a new incident.",
        ) from None
    session.add(
        LogFile(
            incident_id=incident.id,
            original_filename=incident.original_filename or "legacy.log",
            storage_key=path.name,
            storage_scope=storage.scope,
            mime_type="text/plain",
            size_bytes=size,
            sha256=digest.hexdigest(),
        )
    )
    session.flush()


def reset_analysis(incident, has_files):
    incident.statistics = incident.analysis = incident.error_message = incident.severity = None
    incident.completed_at = None
    incident.stored_file_path = None
    incident.status = IncidentStatus.UPLOADED if has_files else IncidentStatus.CREATED


def cleanup_pending(factory, settings):
    """An absent object is already clean; failures retain the queue row for retry."""
    storage = get_storage(settings)
    with factory() as session:
        keys = list(
            session.scalars(
                select(StorageDeletion.storage_key)
                .where(StorageDeletion.storage_scope == storage.scope)
                .order_by(StorageDeletion.created_at)
                .limit(100)
            )
        )
    completed = 0
    for key in keys:
        try:
            with factory() as session:
                row = session.scalar(
                    select(StorageDeletion)
                    .where(StorageDeletion.storage_key == key)
                    .with_for_update()
                )
                if row is None:
                    continue
                # Never delete an object that is still referenced.
                if session.scalar(select(LogFile.id).where(LogFile.storage_key == key)):
                    continue
                storage.delete(key)
                session.delete(row)
                session.commit()
                completed += 1
        except Exception:
            logger.warning("storage.cleanup_deferred")
    return completed


def discard_saved(storage, keys):
    for key in keys:
        try:
            storage.delete(key)
        except (OSError, ValueError):
            logger.error("storage.uncommitted_cleanup_failed")
