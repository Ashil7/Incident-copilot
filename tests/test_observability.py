"""Error privacy, request-context isolation, audit correlation, and readiness."""

import asyncio
import json
import logging
from uuid import UUID

import httpx
import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from app.models import AuditEvent
from app.observability import JsonFormatter, request_id_context
from app.services.storage import LocalStorage


@pytest.fixture
def json_logs():
    records = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(JsonFormatter().format(record))

    handler = Capture()
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)


def test_errors_have_server_request_ids_and_auth_headers(client):
    response = client.get("/api/v1/incidents", headers={"X-Request-ID": "private-client-value"})
    assert response.status_code == 401
    body = response.json()["error"]
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == "INVALID_CREDENTIALS"
    assert str(UUID(body["request_id"])) == response.headers["x-request-id"]
    assert "private-client-value" not in response.text
    assert response.headers["www-authenticate"] == "Bearer"
    assert client.get("/health").headers["x-request-id"] != body["request_id"]


def test_validation_and_unknown_http_details_are_not_echoed(client):
    response = client.post("/api/v1/auth/register", json={"password": "private-password"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "private-password" not in response.text

    @client.app.get("/__test/http-error")
    def fail():
        raise HTTPException(400, "private-error-detail")

    response = client.get("/__test/http-error")
    assert response.status_code == 400
    assert "private-error-detail" not in response.text


@pytest.mark.parametrize("database", [False, True])
def test_unhandled_errors_are_safe_even_in_debug(client, json_logs, database):
    @client.app.get("/__test/failure")
    def fail():
        if database:
            raise OperationalError("private SQL", {}, Exception("private-exception-secret"))
        raise RuntimeError("private-exception-secret")

    client.app.debug = True
    client.app.middleware_stack = None
    response = client.get("/__test/failure")
    assert response.status_code == (503 if database else 500)
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
    assert "private-exception-secret" not in response.text + "".join(json_logs)
    assert "private SQL" not in "".join(json_logs)
    assert any(json.loads(row)["event"] == "request.failed" for row in json_logs)


def test_request_logs_use_templates_without_query_or_headers(client, json_logs):
    response = client.get(
        "/private-path-secret?api_key=private-query-secret",
        headers={"Authorization": "Bearer private-token-secret"},
    )
    data = json.loads(json_logs[-1])
    assert data["route"] == "unmatched"
    assert data["request_id"] == response.headers["x-request-id"]
    assert data["status_code"] == 404
    assert data["duration_ms"] >= 0
    assert "private-" not in "".join(json_logs)


def test_audit_and_background_logs_share_request_id(client, incident_user, json_logs):
    response = client.post(
        "/api/v1/incidents",
        data={"title": "private-title-secret"},
        files={"log_file": ("private-name.log", b"INFO GET /health 200 10ms", "text/plain")},
    )
    assert response.status_code == 202
    request_id = response.headers["x-request-id"]
    with client.app.state.session_factory() as session:
        events = list(session.scalars(select(AuditEvent)))
        assert events
        assert all(event.request_id == request_id for event in events)
    completed = [
        json.loads(row) for row in json_logs if json.loads(row)["event"] == "analysis.completed"
    ]
    assert completed[0]["request_id"] == request_id
    assert completed[0]["incident_id"] == response.json()["id"]
    assert "private-title-secret" not in "".join(json_logs)
    assert "private-name.log" not in "".join(json_logs)
    assert request_id_context.get() is None


def test_parallel_request_context_is_isolated(client):
    @client.app.get("/__test/context")
    async def context():
        before = request_id_context.get()
        await asyncio.sleep(0)
        return {"before": before, "after": request_id_context.get()}

    async def requests():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client.app), base_url="http://test"
        ) as async_client:
            return await asyncio.gather(*(async_client.get("/__test/context") for _ in range(4)))

    responses = asyncio.run(requests())
    assert len({response.headers["x-request-id"] for response in responses}) == 4
    assert all(
        response.json()["before"] == response.json()["after"] == response.headers["x-request-id"]
        for response in responses
    )
    assert request_id_context.get() is None


def test_background_exception_is_logged_without_replacing_sent_response(client, json_logs):
    def failed():
        raise RuntimeError("private-background-secret")

    @client.app.post("/__test/background", status_code=202)
    def background(tasks: BackgroundTasks):
        tasks.add_task(failed)
        return {"accepted": True}

    assert client.post("/__test/background").status_code == 202
    assert any(json.loads(row)["event"] == "background.failed" for row in json_logs)
    assert "private-background-secret" not in "".join(json_logs)


def test_schema_readiness_failure_does_not_break_liveness(client, database_engine):
    with database_engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'old'"))
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SCHEMA_NOT_READY"
    assert client.get("/health/live").status_code == 200
    assert client.get("/health").status_code == 200


def test_storage_readiness_failure_is_safe(client, monkeypatch):
    def fail(self):
        raise PermissionError("private-storage-path")

    monkeypatch.setattr(LocalStorage, "check_ready", fail)
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert "private-storage-path" not in response.text
    assert client.get("/health/live").status_code == 200


def test_formatter_ignores_messages_arguments_and_exceptions():
    record = logging.LogRecord(
        "app", logging.ERROR, "private.py", 1, "private-message %s", ("private-argument",), None
    )
    assert "private" not in JsonFormatter().format(record)


def test_observability_smoke_script_with_admin(client):
    from app.models import User, UserRole
    from app.services.auth import password_hasher
    from scripts.verify_observability import verify

    credentials = ("observability@example.com", "Synthetic-password-123!")
    with client.app.state.session_factory() as session:
        session.add(
            User(
                email=credentials[0],
                full_name="Observability test",
                role=UserRole.ADMIN,
                password_hash=password_hasher.hash(credentials[1]),
            )
        )
        session.commit()
    verify(client, credentials)
