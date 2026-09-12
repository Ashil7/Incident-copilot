"""Offline database lifecycle, transaction, and readiness checks."""

from collections.abc import Iterator
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_session_factory, get_db
from app.models import Incident, IncidentStatus
from app.schemas import IncidentResponse


def test_migrated_table_is_available(client: TestClient, database_engine: Engine) -> None:
    assert inspect(database_engine).has_table("incidents")


def test_commit_refresh_and_rollback(client: TestClient, database_engine: Engine) -> None:
    factory = create_session_factory(database_engine)
    with factory() as session:
        incident = Incident(title="Synthetic incident", stored_file_path="private/path.log")
        session.add(incident)
        session.commit()
        session.refresh(incident)
        incident_id = incident.id
        assert str(UUID(incident_id)) == incident_id
        assert incident.status == IncidentStatus.CREATED
        assert "stored_file_path" not in IncidentResponse.model_validate(incident).model_dump()
        incident.title = "Uncommitted edit"
        session.flush()
        session.rollback()
    with factory() as session:
        assert session.get(Incident, incident_id).title == "Synthetic incident"


def test_readiness_success(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_database_failure_does_not_leak_or_break_liveness(client: TestClient) -> None:
    session = MagicMock(spec=Session)
    session.connection.side_effect = OperationalError("SELECT 1", {}, Exception("secret-password"))

    def unavailable_db() -> Iterator[Session]:
        yield session

    client.app.dependency_overrides[get_db] = unavailable_db
    try:
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
        assert response.json()["error"]["message"] == "Database unavailable."
        assert response.json()["error"]["request_id"] == response.headers["x-request-id"]
        assert "secret-password" not in response.text
        assert client.get("/health").status_code == 200
    finally:
        client.app.dependency_overrides.clear()


@pytest.mark.parametrize("failed", [False, True])
def test_session_dependency_always_exits(failed: bool) -> None:
    request = MagicMock(spec=Request)
    manager = request.app.state.session_factory.return_value
    dependency = get_db(request)
    assert next(dependency) is manager.__enter__.return_value
    if failed:
        with pytest.raises(ValueError):
            dependency.throw(ValueError("synthetic request failure"))
    else:
        with pytest.raises(StopIteration):
            next(dependency)
    manager.__exit__.assert_called_once()


def test_missing_database_url_fails_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    from app.main import create_app

    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        with TestClient(create_app(Settings(_env_file=None))):
            pass


def test_failed_startup_disposes_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    from app.main import create_app

    engine = MagicMock(spec=Engine)
    failure = OperationalError("synthetic", {}, Exception("private-details"))
    monkeypatch.setattr("app.main.verify_schema", MagicMock(side_effect=failure))
    with pytest.raises(RuntimeError, match="Database startup failed") as error:
        with TestClient(create_app(Settings(_env_file=None), database_engine=engine)):
            pass
    assert "private-details" not in str(error.value)
    engine.dispose.assert_called_once()
