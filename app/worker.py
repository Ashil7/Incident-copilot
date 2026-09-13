"""Separate worker process with task-owned database connections."""

import argparse
import logging
from uuid import UUID

from celery.signals import setup_logging
from sqlalchemy import select

from app.config import Settings
from app.container import container_settings
from app.database import create_database_engine, create_session_factory
from app.migration_state import verify_schema
from app.models import Incident, IncidentStatus
from app.observability import JsonFormatter, configure_logging, log_event, request_id_context
from app.services.incident_files import cleanup_pending
from app.services.jobs import RetryJob, SupersededAttempt, active_job, new_job, run_job
from app.task_queue import RUNBOOK_TASK_NAME, TASK_NAME, create_celery


def process(incident_id, request_id, settings, *, analyze=True, cleanup=False, job_id=None):
    incident_id = str(UUID(incident_id))
    request_id = str(UUID(request_id)) if request_id else None
    token = request_id_context.set(request_id)
    engine = None
    try:
        engine = create_database_engine(settings)
        with engine.connect() as connection:
            verify_schema(connection)
        factory = create_session_factory(engine)
        if job_id is None:
            # Compatibility for messages queued before the migration. Never bypass jobs.
            with factory() as session:
                incident = session.scalar(
                    select(Incident).where(Incident.id == incident_id).with_for_update()
                )
                if incident is None:
                    return
                job = active_job(session, incident_id)
                if job is None:
                    if not analyze:
                        cleanup_pending(factory, settings)
                        return
                    if incident.status != IncidentStatus.UPLOADED:
                        return
                    job = new_job(session, incident, analyze=analyze, cleanup=cleanup)
                    session.commit()
                job_id = job.id
        run_job(str(UUID(job_id)), factory, settings)
    except RetryJob:
        raise
    except SupersededAttempt:
        return
    except Exception:
        log_event("worker.failed", level=logging.ERROR, incident_id=incident_id)
        raise RuntimeError(
            "Worker processing failed; inspect incident state and readiness."
        ) from None
    finally:
        if engine is not None:
            engine.dispose()
        request_id_context.reset(token)


def create_worker(settings):
    application = create_celery(settings)

    @application.task(name=TASK_NAME, shared=False, bind=True, max_retries=10)
    def task(self, incident_id, request_id=None, analyze=True, cleanup=False, job_id=None):
        try:
            process(
                incident_id, request_id, settings, analyze=analyze, cleanup=cleanup, job_id=job_id
            )
        except RetryJob as error:
            raise self.retry(exc=RuntimeError("Controlled job retry."), countdown=error.delay)
        except RuntimeError:
            # Infrastructure failures before job state can be persisted are bounded too.
            raise self.retry(exc=RuntimeError("Worker infrastructure unavailable."), countdown=30)

    @application.task(name=RUNBOOK_TASK_NAME, shared=False, bind=True, max_retries=3)
    def runbook_task(self, runbook_id, request_id=None):
        token = request_id_context.set(request_id)
        engine = None
        try:
            engine = create_database_engine(settings)
            with engine.connect() as connection:
                verify_schema(connection)
            from app.services.runbooks import index_runbook

            with create_session_factory(engine)() as session:
                index_runbook(session, str(UUID(runbook_id)), settings)
        except Exception:
            raise self.retry(
                exc=RuntimeError("Runbook indexing infrastructure unavailable."), countdown=30
            ) from None
        finally:
            if engine is not None:
                engine.dispose()
            request_id_context.reset(token)

    return application


def safe_worker_logging(**kwargs):
    configure_logging()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.getLogger().handlers = [handler]
    logging.getLogger().setLevel(logging.INFO)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    if args.container:
        settings = container_settings(settings)
    setup_logging.connect(safe_worker_logging, weak=False)
    application = create_worker(settings)
    application.worker_main(
        ["--quiet", "worker", "--loglevel=INFO", "--concurrency=1", "--hostname=incident-worker@%h"]
    )


if __name__ == "__main__":
    main()
