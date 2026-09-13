"""Durable job state, attempt fencing, and incident-wide execution locks."""

import hashlib
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.errors import DomainError
from app.models import AnalysisJob, Incident, IncidentStatus
from app.observability import log_event, request_id_context
from app.services.ai_provider import TransientProviderError
from app.services.incident_files import cleanup_pending
from app.services.pipeline import perform_analysis

ACTIVE = ("PENDING", "RUNNING", "RETRY")
SAFE_FAILURE = (
    "Analysis failed. Check model configuration, provider availability, and uploaded data."
)
_test_locks = {}
_test_guard = threading.Lock()


class RetryJob(Exception):
    def __init__(self, delay):
        super().__init__("Job is waiting for a controlled retry.")
        self.delay = delay


class SupersededAttempt(Exception):
    pass


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def active_job(session, incident_id):
    return session.scalar(
        select(AnalysisJob).where(
            AnalysisJob.incident_id == incident_id, AnalysisJob.status.in_(ACTIVE)
        )
    )


def new_job(session, incident, *, analyze=True, cleanup=False):
    """Caller holds the incident row lock (or is creating it) and commits atomically."""
    if active_job(session, incident.id):
        raise DomainError("ANALYSIS_ACTIVE")
    job_id = str(uuid4())
    job = AnalysisJob(
        id=job_id,
        incident_id=incident.id,
        celery_task_id=job_id,
        request_id=request_id_context.get(),
        analyze=analyze,
        cleanup=cleanup,
        status="PENDING",
        current_stage="QUEUED",
        progress=0,
        attempt_count=0,
    )
    session.add(job)
    session.flush()
    return job


@contextmanager
def incident_lock(engine, incident_id):
    """Session advisory lock survives stage commits; a dead connection releases it."""
    if engine.dialect.name == "sqlite":
        # SQLite is used only by offline tests; production configuration requires PG.
        with _test_guard:
            lock = _test_locks.setdefault(incident_id, threading.Lock())
        acquired = lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                lock.release()
        return
    key = int.from_bytes(hashlib.sha256(incident_id.encode()).digest()[:8], "big", signed=True)
    with engine.connect() as connection:
        acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key})
        connection.commit()
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    connection.commit()
                except Exception:
                    connection.invalidate()


def transient(error):
    return isinstance(error, (TransientProviderError, OperationalError))


def run_job(job_id, factory, settings):
    with factory() as session:
        job = session.get(AnalysisJob, job_id)
        if job is None or job.status not in ACTIVE:
            return
        incident_id, request_id = job.incident_id, job.request_id
    token = request_id_context.set(request_id)
    try:
        with incident_lock(factory.kw["bind"], incident_id) as acquired:
            if not acquired:
                raise RetryJob(5)
            execute_job(job_id, factory, settings)
    finally:
        request_id_context.reset(token)


def execute_job(job_id, factory, settings):
    attempt = None
    try:
        with factory() as session:
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job is None or job.status not in ACTIVE:
                return
            incident = session.get(Incident, job.incident_id)
            now = datetime.now(timezone.utc)
            if job.retry_at and aware(job.retry_at) > now:
                raise RetryJob(max(1, int((aware(job.retry_at) - now).total_seconds()) + 1))
            if job.attempt_count >= settings.analysis_max_attempts:
                job.status, job.error_code, job.error_message = (
                    "FAILED",
                    "ATTEMPTS_EXHAUSTED",
                    SAFE_FAILURE,
                )
                job.finished_at = now
                incident.status, incident.error_message, incident.completed_at = (
                    IncidentStatus.FAILED,
                    SAFE_FAILURE,
                    now,
                )
                session.commit()
                return
            job.attempt_count += 1
            attempt = job.attempt_count
            job.started_at = job.started_at or now
            job.status, job.retry_at = "RUNNING", None
            job.error_code = job.error_message = None
            session.commit()
            log_event("worker.started", incident_id=incident.id, job_id=job.id)

            def stage(status):
                current = session.scalar(
                    select(AnalysisJob)
                    .where(AnalysisJob.id == job_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if current.attempt_count != attempt or current.status != "RUNNING":
                    raise SupersededAttempt()
                incident.status = status
                current.current_stage = status.value
                progress = {
                    IncidentStatus.PARSING: 10,
                    IncidentStatus.CALCULATING: 40 if incident.statistics else 25,
                    IncidentStatus.GENERATING_ANALYSIS: 60,
                    IncidentStatus.VALIDATING: 85,
                    IncidentStatus.COMPLETED: 100,
                }[status]
                current.progress = max(current.progress, progress)
                if status == IncidentStatus.COMPLETED:
                    current.status, current.finished_at = "COMPLETED", datetime.now(timezone.utc)
                session.commit()

            if job.cleanup:
                cleanup_pending(factory, settings)
            if job.analyze:
                resume = incident.statistics is not None and job.progress >= 40
                stage(IncidentStatus.PARSING if not resume else IncidentStatus.CALCULATING)
                perform_analysis(session, incident, settings, stage, resume=resume)
            else:
                # Cleanup rows are independently durable; no analysis for an empty file set.
                session.refresh(job, with_for_update=True)
                if job.attempt_count != attempt or job.status != "RUNNING":
                    raise SupersededAttempt()
                job.status, job.progress, job.current_stage = "COMPLETED", 100, "CLEANUP"
                job.finished_at = datetime.now(timezone.utc)
                session.commit()
            log_event("analysis.completed", incident_id=incident.id, job_id=job_id)
    except (RetryJob, SupersededAttempt):
        raise
    except Exception as error:
        if attempt is None:
            raise
        retry = transient(error) and attempt < settings.analysis_max_attempts
        delay = min(settings.analysis_retry_seconds * (2 ** (attempt - 1)), 300)
        with factory() as session:
            job = session.scalar(
                select(AnalysisJob).where(AnalysisJob.id == job_id).with_for_update()
            )
            if job.attempt_count != attempt or job.status != "RUNNING":
                return
            incident = session.get(Incident, job.incident_id)
            job.status = "RETRY" if retry else "FAILED"
            job.error_code = "TRANSIENT_FAILURE" if retry else "ANALYSIS_FAILED"
            job.error_message = SAFE_FAILURE
            job.retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay) if retry else None
            job.finished_at = None if retry else datetime.now(timezone.utc)
            incident.analysis = None
            incident.status = IncidentStatus.UPLOADED if retry else IncidentStatus.FAILED
            incident.error_message = None if retry else SAFE_FAILURE
            incident.completed_at = job.finished_at
            session.commit()
            log_event(
                "analysis.retry" if retry else "analysis.failed",
                level=logging.WARNING if retry else logging.ERROR,
                incident_id=incident.id,
                job_id=job.id,
                error_code=job.error_code,
            )
        if retry:
            raise RetryJob(delay) from None
