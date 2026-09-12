"""Isolated settings and an in-process API client for foundation tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def database_engine() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    yield engine
    engine.dispose()


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, database_engine: Engine, tmp_path: Path
) -> Iterator[TestClient]:
    # Prevent even the module-level app from reading the developer's .env.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    from app.main import create_app

    settings = Settings(_env_file=None, app_env="test", upload_directory=tmp_path / "uploads")
    with TestClient(create_app(settings, database_engine=database_engine)) as test_client:
        yield test_client
