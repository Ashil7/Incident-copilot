"""Isolated settings and an in-process API client for foundation tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from scripts.migrate import upgrade_database


@pytest.fixture
def incident_user(client):
    from app.models import User
    from app.services.auth import issue_tokens

    with client.app.state.session_factory() as session:
        user = User(
            email="incident-test@example.com", full_name="Incident test", password_hash="unused"
        )
        session.add(user)
        session.flush()
        tokens = issue_tokens(session, user, client.app.state.settings)
        session.commit()
    client.headers["Authorization"] = "Bearer " + tokens.access_token
    return user


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def block_live_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*args, **kwargs):
        raise AssertionError("Tests must mock the provider; live API calls are forbidden.")

    monkeypatch.setattr("app.services.openai_provider.OpenAI", blocked)


@pytest.fixture
def database_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.begin() as connection:
        upgrade_database(connection)
    yield engine
    engine.dispose()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, database_engine: Engine, tmp_path: Path
) -> Iterator[TestClient]:
    # Prevent even the module-level app from reading the developer's .env.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    from app.main import create_app

    class InlineTestQueue:
        """Offline adapter only: integration tests use the existing isolated database."""

        def __init__(self, settings):
            self.settings = settings

        def check_ready(self):
            pass

        def close(self):
            pass

        def enqueue(self, incident_id, request_id, *, analyze=True, cleanup=False, job_id=None):
            from app.database import create_session_factory
            from app.services.jobs import RetryJob, run_job

            factory = create_session_factory(database_engine)
            try:
                run_job(job_id, factory, self.settings)
            except RetryJob:
                pass  # Explicit retry tests advance the persisted due time.

        def enqueue_runbook(self, runbook_id, request_id):
            pass

    monkeypatch.setattr("app.main.TaskQueue", InlineTestQueue)

    settings = Settings(
        _env_file=None,
        app_env="test",
        upload_directory=tmp_path / "uploads",
        jwt_secret_key="synthetic-test-key-only-32-bytes-long",
        allow_registration=True,
    )
    with TestClient(create_app(settings, database_engine=database_engine)) as test_client:
        yield test_client
