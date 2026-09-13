"""Durable attempts, recovery, checkpoints, and authorization without external calls."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import AnalysisJob, Incident, IncidentStatus, User
from app.services.ai_provider import TransientProviderError
from app.services.auth import issue_tokens
from app.services.jobs import RetryJob, incident_lock, run_job
from scripts.recover_jobs import recover


def upload(client, body=b"INFO GET /health 200 10ms"):
    response = client.post(
        "/api/v1/incidents",
        data={"title": "Job test"},
        files={"log_file": ("test.log", body, "text/plain")},
    )
    assert response.status_code == 202
    return response.json()["id"]


def job(client, incident_id):
    response = client.get(f"/api/v1/incidents/{incident_id}/jobs/latest")
    assert response.status_code == 200
    return response.json()


def run(client, job_id):
    run_job(job_id, client.app.state.session_factory, client.app.state.settings)


def due(client, job_id):
    with client.app.state.session_factory() as session:
        session.get(AnalysisJob, job_id).retry_at = datetime.now(timezone.utc) - timedelta(
            seconds=1
        )
        session.commit()


def test_progress_completed_and_repeated_delivery(client, incident_user, monkeypatch):
    incident_id = upload(client)
    result = job(client, incident_id)
    assert (result["status"], result["progress"], result["attempt_count"]) == ("COMPLETED", 100, 1)
    assert result["started_at"] and result["finished_at"]
    assert "celery_task_id" not in result and "request_id" not in result
    provider = MagicMock(side_effect=AssertionError("Terminal jobs never execute"))
    monkeypatch.setattr("app.services.pipeline.generate_analysis", provider)
    run(client, result["id"])
    assert job(client, incident_id) == result
    provider.assert_not_called()


def test_latest_normalized_analysis_is_private_and_has_metadata(client, incident_user):
    incident_id = upload(client)
    path = f"/api/v1/incidents/{incident_id}/analysis"
    response = client.get(path)
    assert response.status_code == 200
    body = response.json()
    assert body["incident_id"] == incident_id
    assert body["provider"] == "deterministic"
    assert body["model"] is None and body["prompt_version"] is None
    assert body["input_tokens"] is None and body["output_tokens"] is None
    assert body["duration_seconds"] == 0
    with client.app.state.session_factory() as session:
        other = User(
            email="analysis-private@example.com", full_name="Other", password_hash="unused"
        )
        session.add(other)
        session.flush()
        token = issue_tokens(session, other, client.app.state.settings).access_token
        session.commit()
    headers = {"Authorization": "Bearer " + token}
    assert client.get(path, headers=headers).status_code == 404
    assert client.get(f"/api/v1/incidents/{uuid4()}/analysis").status_code == 404


def test_active_job_prevents_duplicate_analysis_and_file_edit(client, incident_user, monkeypatch):
    monkeypatch.setattr(client.app.state.task_queue, "enqueue", lambda *args, **kwargs: None)
    incident_id = upload(client)
    path = f"/api/v1/incidents/{incident_id}"
    assert client.post(path + "/analysis").status_code == 409
    assert client.post(path + "/analysis/retry").status_code == 409
    assert (
        client.post(
            path + "/files", files={"log_files": ("new.log", b"INFO", "text/plain")}
        ).status_code
        == 409
    )
    with client.app.state.session_factory() as session:
        session.add(AnalysisJob(incident_id=incident_id))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_transient_retry_resumes_statistics_and_is_bounded(client, incident_user, monkeypatch):
    failure = MagicMock(side_effect=TransientProviderError("synthetic transient failure"))
    monkeypatch.setattr("app.services.pipeline.generate_analysis", failure)
    incident_id = upload(client, b"ERROR GET /api 500 10ms")
    first = job(client, incident_id)
    assert first["status"] == "RETRY" and first["attempt_count"] == 1
    assert first["progress"] == 60 and first["retry_at"]
    job_id = first["id"]
    with pytest.raises(RetryJob):
        run(client, job_id)  # Delayed delivery must not consume another attempt.
    assert job(client, incident_id)["attempt_count"] == 1
    monkeypatch.setattr(
        "app.services.pipeline.parse_incident_files",
        MagicMock(side_effect=AssertionError("Checkpoint must be reused")),
    )
    due(client, job_id)
    with pytest.raises(RetryJob) as retry:
        run(client, job_id)
    assert retry.value.delay == 2 * client.app.state.settings.analysis_retry_seconds
    due(client, job_id)
    run(client, job_id)
    final = job(client, incident_id)
    assert (final["status"], final["attempt_count"]) == ("FAILED", 3)
    assert failure.call_count == 3
    assert "synthetic transient" not in str(final)


def test_validation_failure_is_not_retried_and_manual_retry_gets_new_job(
    client, incident_user, monkeypatch
):
    monkeypatch.setattr(
        "app.services.pipeline.generate_analysis", lambda *args: {"result": {"private": "bad"}}
    )
    incident_id = upload(client, b"ERROR GET /api 500 10ms")
    failed = job(client, incident_id)
    assert failed["status"] == "FAILED" and failed["attempt_count"] == 1
    assert failed["retry_at"] is None and "private" not in str(failed)
    monkeypatch.setattr(client.app.state.task_queue, "enqueue", lambda *args, **kwargs: None)
    response = client.post(f"/api/v1/incidents/{incident_id}/analysis/retry")
    assert response.status_code == 202
    assert response.json()["id"] != failed["id"]
    assert response.json()["attempt_count"] == 0
    run(client, failed["id"])  # A stale message cannot alter the new active job.
    assert job(client, incident_id)["status"] == "PENDING"


def test_recovery_republishes_same_durable_job(client, incident_user, monkeypatch):
    publish = MagicMock(side_effect=OSError("private broker failure"))
    monkeypatch.setattr(client.app.state.task_queue, "enqueue", publish)
    response = client.post(
        "/api/v1/incidents",
        data={"title": "Saved but unpublished"},
        files={"log_file": ("test.log", b"INFO", "text/plain")},
    )
    assert response.status_code == 503
    with client.app.state.session_factory() as session:
        saved = session.scalar(select(AnalysisJob))
        job_id = saved.id
    queue = MagicMock()
    assert recover(client.app.state.session_factory, queue) == 1
    assert queue.enqueue.call_args.kwargs["job_id"] == job_id
    run(client, job_id)
    assert recover(client.app.state.session_factory, queue) == 0


def test_interrupted_job_resumes_and_concurrent_delivery_waits(client, incident_user, monkeypatch):
    monkeypatch.setattr(client.app.state.task_queue, "enqueue", lambda *args, **kwargs: None)
    incident_id = upload(client)
    job_id = job(client, incident_id)["id"]
    factory = client.app.state.session_factory
    with incident_lock(factory.kw["bind"], incident_id) as locked:
        assert locked
        with pytest.raises(RetryJob):
            run(client, job_id)
    with factory() as session:
        saved = session.get(AnalysisJob, job_id)
        saved.status, saved.attempt_count, saved.progress = "RUNNING", 1, 10
        session.get(Incident, incident_id).status = IncidentStatus.PARSING
        session.commit()
    run(client, job_id)
    assert job(client, incident_id)["status"] == "COMPLETED"
    assert job(client, incident_id)["attempt_count"] == 2


def test_job_permissions_and_retry_state(client, incident_user):
    incident_id = upload(client)
    path = f"/api/v1/incidents/{incident_id}"
    assert client.post(path + "/analysis/retry").status_code == 409
    with client.app.state.session_factory() as session:
        other = User(email="other-job@example.com", full_name="Other", password_hash="unused")
        session.add(other)
        session.flush()
        token = issue_tokens(session, other, client.app.state.settings).access_token
        session.commit()
    headers = {"Authorization": "Bearer " + token}
    assert client.get(path + "/jobs/latest", headers=headers).status_code == 404
    assert client.post(path + "/analysis/retry", headers=headers).status_code == 404
    assert client.post(path + "/analysis", headers=headers).status_code == 404
    assert client.get(f"/api/v1/incidents/{uuid4()}/jobs/latest").status_code == 404


def test_crash_attempt_budget_stops_poison_job(client, incident_user, monkeypatch):
    monkeypatch.setattr(client.app.state.task_queue, "enqueue", lambda *args, **kwargs: None)
    incident_id = upload(client)
    job_id = job(client, incident_id)["id"]
    with client.app.state.session_factory() as session:
        saved = session.get(AnalysisJob, job_id)
        saved.attempt_count = client.app.state.settings.analysis_max_attempts
        saved.status = "RUNNING"
        session.commit()
    run(client, job_id)
    assert job(client, incident_id)["error_code"] == "ATTEMPTS_EXHAUSTED"


def test_live_job_script_contract(client, incident_user):
    from app.services.auth import password_hasher
    from scripts.verify_jobs import verify

    with client.app.state.session_factory() as session:
        user = session.get(User, incident_user.id)
        user.password_hash = password_hasher.hash("Synthetic-password-123!")
        session.commit()
    verify(client, incident_user.email, "Synthetic-password-123!")


def test_superseded_attempt_cannot_commit(client, incident_user, monkeypatch):
    from app.services.jobs import SupersededAttempt

    monkeypatch.setattr(client.app.state.task_queue, "enqueue", lambda *args, **kwargs: None)
    incident_id = upload(client)
    job_id = job(client, incident_id)["id"]

    def supersede(session, incident, settings, stage, **kwargs):
        with client.app.state.session_factory() as other:
            other.get(AnalysisJob, job_id).attempt_count += 1
            other.commit()
        incident.analysis = {"should_not": "be saved"}
        stage(IncidentStatus.COMPLETED)

    monkeypatch.setattr("app.services.jobs.perform_analysis", supersede)
    with pytest.raises(SupersededAttempt):
        run(client, job_id)
    with client.app.state.session_factory() as session:
        assert session.get(Incident, incident_id).analysis is None


def test_worker_requests_safe_celery_retry(monkeypatch):
    from app.config import Settings
    from app.task_queue import TASK_NAME
    from app.worker import create_worker

    monkeypatch.setattr("app.worker.process", MagicMock(side_effect=RetryJob(7)))
    application = create_worker(Settings(_env_file=None))
    task = application.tasks[TASK_NAME]
    retry = MagicMock(side_effect=RuntimeError("Retry scheduled"))
    monkeypatch.setattr(task, "retry", retry)
    try:
        with pytest.raises(RuntimeError, match="Retry scheduled"):
            task.run(str(uuid4()), job_id=str(uuid4()))
        assert retry.call_args.kwargs["countdown"] == 7
        assert str(retry.call_args.kwargs["exc"]) == "Controlled job retry."
        assert application.conf.task_acks_late is True
        assert application.conf.task_reject_on_worker_lost is True
    finally:
        application.close()
