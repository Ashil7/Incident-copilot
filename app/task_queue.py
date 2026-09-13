"""JSON-only Celery messages contain identifiers, never credentials or uploaded text."""

import logging
from uuid import UUID

from celery import Celery
from redis import Redis

from app.errors import DomainError
from app.observability import log_event, request_id_context

TASK_NAME = "incident.process"
RUNBOOK_TASK_NAME = "runbook.index"
QUEUE_NAME = "incidents"


def create_celery(settings):
    application = Celery("incident_copilot", broker=settings.redis_url.get_secret_value())
    application.conf.update(
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,
        task_default_queue=QUEUE_NAME,
        task_publish_retry=False,
        broker_connection_timeout=3,
        broker_transport_options={"socket_connect_timeout": 3, "socket_timeout": 3},
        broker_connection_retry_on_startup=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_soft_time_limit=600,
        task_time_limit=630,
        worker_hijack_root_logger=False,
        worker_redirect_stdouts=False,
    )
    return application


class TaskQueue:
    def __init__(self, settings):
        self.application = create_celery(settings)
        self.redis = Redis.from_url(
            settings.redis_url.get_secret_value(), socket_connect_timeout=3, socket_timeout=3
        )

    def check_ready(self):
        self.redis.ping()

    def enqueue(self, incident_id, request_id, *, analyze=True, cleanup=False, job_id=None):
        incident_id = str(UUID(incident_id))
        request_id = str(UUID(request_id)) if request_id else None
        job_id = str(UUID(job_id)) if job_id else None
        self.application.send_task(
            TASK_NAME,
            kwargs={
                "incident_id": incident_id,
                "request_id": request_id,
                "analyze": analyze,
                "cleanup": cleanup,
                "job_id": job_id,
            },
            **({"task_id": job_id} if job_id else {}),
        )

    def enqueue_runbook(self, runbook_id, request_id):
        self.application.send_task(
            RUNBOOK_TASK_NAME,
            kwargs={
                "runbook_id": str(UUID(runbook_id)),
                "request_id": str(UUID(request_id)) if request_id else None,
            },
        )

    def close(self):
        self.redis.close()
        self.application.close()


def enqueue_processing(request, incident_id, *, analyze=True, cleanup=False, job_id=None):
    """Publish only after the caller committed file metadata and incident state."""
    try:
        request.app.state.task_queue.enqueue(
            incident_id, request_id_context.get(), analyze=analyze, cleanup=cleanup, job_id=job_id
        )
    except Exception:
        # Publish outcomes can be ambiguous: do not change state or remove committed
        # files, since a worker may already have received this message.
        log_event("queue.publish_failed", level=logging.ERROR, incident_id=incident_id)
        raise DomainError("QUEUE_UNAVAILABLE") from None


def enqueue_runbook(request, runbook_id):
    try:
        request.app.state.task_queue.enqueue_runbook(runbook_id, request_id_context.get())
    except Exception:
        log_event("queue.publish_failed", level=logging.ERROR, runbook_id=runbook_id)
        raise DomainError("QUEUE_UNAVAILABLE") from None
