"""Queue contracts without live Redis, PostgreSQL, or model calls."""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import select

from app.config import Settings
from app.models import AnalysisJob, Incident, IncidentStatus, LogFile
from app.observability import request_id_context
from app.task_queue import TASK_NAME, TaskQueue, create_celery
from app.worker import create_worker, process


def upload(client):
    return client.post(
        "/api/v1/incidents",
        data={"title": "Queued synthetic incident"},
        files={"log_file": ("healthy.log", b"INFO GET /health 200 10ms", "text/plain")},
    )


def test_publish_after_commit_and_no_inline_analysis(client, incident_user, monkeypatch):
    calls = []

    def capture(incident_id, request_id, **kwargs):
        with client.app.state.session_factory() as session:
            assert session.get(Incident, incident_id).status == IncidentStatus.UPLOADED
            assert session.scalar(select(LogFile).where(LogFile.incident_id == incident_id))
        calls.append((incident_id, request_id, kwargs))

    monkeypatch.setattr(client.app.state.task_queue, "enqueue", capture)
    response = upload(client)
    assert response.status_code == 202
    incident_id = response.json()["id"]
    job_id = client.get(f"/api/v1/incidents/{incident_id}/jobs/latest").json()["id"]
    assert calls == [
        (
            incident_id,
            response.headers["x-request-id"],
            {"analyze": True, "cleanup": False, "job_id": job_id},
        )
    ]
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["status"] == "UPLOADED" and detail["analysis"] is None


def test_publish_failure_retains_committed_data(client, incident_user, monkeypatch):
    monkeypatch.setattr(
        client.app.state.task_queue, "enqueue", MagicMock(side_effect=ConnectionError("secret-url"))
    )
    response = upload(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    assert "secret-url" not in response.text
    with client.app.state.session_factory() as session:
        assert session.scalar(select(Incident)).status == IncidentStatus.UPLOADED
        assert session.scalar(select(LogFile)) is not None
    assert len(list(client.app.state.settings.upload_directory.glob("*.log"))) == 1


def test_redis_readiness_failure_preserves_liveness(client, monkeypatch):
    monkeypatch.setattr(
        client.app.state.task_queue,
        "check_ready",
        MagicMock(side_effect=ConnectionError("private")),
    )
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    assert "private" not in response.text
    assert client.get("/health/live").status_code == 200


def test_json_message_contains_only_identifiers_and_flags(monkeypatch):
    application = MagicMock()
    monkeypatch.setattr("app.task_queue.create_celery", lambda settings: application)
    redis = MagicMock()
    monkeypatch.setattr("app.task_queue.Redis.from_url", lambda *args, **kwargs: redis)
    queue = TaskQueue(Settings(_env_file=None))
    incident_id, request_id = str(uuid4()), str(uuid4())
    queue.enqueue(incident_id, request_id, cleanup=True)
    application.send_task.assert_called_once_with(
        TASK_NAME,
        kwargs={
            "incident_id": incident_id,
            "request_id": request_id,
            "analyze": True,
            "cleanup": True,
            "job_id": None,
        },
    )
    queue.check_ready()
    redis.ping.assert_called_once()
    queue.close()
    redis.close.assert_called_once()
    application.close.assert_called_once()


def test_celery_config_and_registered_task(monkeypatch):
    settings = Settings(_env_file=None)
    called = MagicMock()
    monkeypatch.setattr("app.worker.process", called)
    application = create_worker(settings)
    try:
        assert application.conf.accept_content == ["json"]
        assert application.conf.task_ignore_result
        assert application.conf.task_publish_retry is False
        assert application.conf.worker_prefetch_multiplier == 1
        assert application.conf.result_backend is None
        incident_id, request_id = str(uuid4()), str(uuid4())
        result = application.tasks[TASK_NAME].apply(
            kwargs={"incident_id": incident_id, "request_id": request_id, "cleanup": True},
            throw=True,
        )
        assert result.successful()
        called.assert_called_once_with(
            incident_id, request_id, settings, analyze=True, cleanup=True, job_id=None
        )
    finally:
        application.close()


@pytest.mark.parametrize("failed", [False, True])
def test_worker_owns_engine_and_resets_context(monkeypatch, failed):
    engine, factory = MagicMock(), MagicMock()
    monkeypatch.setattr("app.worker.create_database_engine", lambda settings: engine)
    monkeypatch.setattr("app.worker.create_session_factory", lambda value: factory)
    monkeypatch.setattr("app.worker.verify_schema", lambda value: None)
    incident_id, request_id = str(uuid4()), str(uuid4())

    def analyze(value, sessions, settings):
        assert value == incident_id and sessions is factory
        assert request_id_context.get() == request_id
        if failed:
            raise RuntimeError("private failure")

    monkeypatch.setattr("app.worker.run_job", analyze)
    outer = request_id_context.set("outer")
    try:
        if failed:
            with pytest.raises(RuntimeError, match="Worker processing failed") as error:
                process(incident_id, request_id, Settings(_env_file=None), job_id=incident_id)
            assert "private" not in str(error.value)
        else:
            process(incident_id, request_id, Settings(_env_file=None), job_id=incident_id)
        engine.dispose.assert_called_once()
        assert request_id_context.get() == "outer"
    finally:
        request_id_context.reset(outer)


def test_broker_configuration_does_not_connect():
    application = create_celery(Settings(_env_file=None))
    application.close()


def test_attach_and_delete_dispatch_after_commit(client, incident_user, monkeypatch):
    incident_id = upload(client).json()["id"]
    calls = MagicMock()
    monkeypatch.setattr(client.app.state.task_queue, "enqueue", calls)
    path = f"/api/v1/incidents/{incident_id}/files"
    assert (
        client.post(path, files={"log_files": ("extra.log", b"INFO", "text/plain")}).status_code
        == 202
    )
    assert calls.call_args.kwargs["analyze"] is True
    assert calls.call_args.kwargs["cleanup"] is False
    with client.app.state.session_factory() as session:
        incident = session.get(Incident, incident_id)
        incident.status = IncidentStatus.COMPLETED
        job = session.get(AnalysisJob, calls.call_args.kwargs["job_id"])
        job.status = "COMPLETED"
        session.commit()
    rows = client.get(path).json()
    assert client.delete(path + "/" + rows[0]["id"]).status_code == 204
    assert calls.call_args.kwargs["analyze"] is True
    assert calls.call_args.kwargs["cleanup"] is True


def test_worker_routes_cleanup_through_durable_job(monkeypatch):
    engine = MagicMock()
    monkeypatch.setattr("app.worker.create_database_engine", lambda settings: engine)
    monkeypatch.setattr("app.worker.verify_schema", lambda connection: None)
    monkeypatch.setattr("app.worker.create_session_factory", lambda value: MagicMock())
    job_id = str(uuid4())
    run = MagicMock()
    monkeypatch.setattr("app.worker.run_job", run)
    process(
        str(uuid4()), None, Settings(_env_file=None), analyze=False, cleanup=True, job_id=job_id
    )
    assert run.call_args.args[0] == job_id
    engine.dispose.assert_called_once()


def test_queue_smoke_script(client, incident_user):
    from app.models import User
    from app.services.auth import password_hasher
    from scripts.verify_queue import verify

    with client.app.state.session_factory() as session:
        user = session.get(User, incident_user.id)
        user.password_hash = password_hasher.hash("Synthetic-password-123!")
        session.commit()
    verify(client, incident_user.email, "Synthetic-password-123!")
