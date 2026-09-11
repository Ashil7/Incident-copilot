"""Isolated settings and an in-process API client for foundation tests."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings


@pytest.fixture(autouse=True)
def clean_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Prevent even the module-level app from reading the developer's .env.
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    from app.main import create_app

    settings = Settings(_env_file=None, app_env="test")
    with TestClient(create_app(settings)) as test_client:
        yield test_client
