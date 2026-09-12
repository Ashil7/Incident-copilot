"""Container addressing must preserve credentials and the WSL configuration."""

import pytest
from sqlalchemy.engine import URL, make_url

from app.config import Settings
from app.container import container_settings


def test_container_url_preserves_encoded_credentials() -> None:
    original = URL.create(
        "postgresql+psycopg",
        username="synthetic",
        password="fake@:/?#%secret",
        host="localhost",
        port=5433,
        database="incident_test",
        query={"application_name": "test"},
    )
    settings = Settings(_env_file=None, database_url=original.render_as_string(hide_password=False))
    adapted = make_url(container_settings(settings).database_url.get_secret_value())
    assert adapted == original.set(host="db", port=5432)
    assert make_url(settings.database_url.get_secret_value()) == original


def test_container_requires_database_url() -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        container_settings(Settings(_env_file=None))
