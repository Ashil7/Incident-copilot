"""Settings loading and validation without developer secrets."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_need_no_credentials() -> None:
    settings = Settings(_env_file=None)
    assert settings.app_env == "development"
    assert settings.debug is False
    assert settings.database_url.get_secret_value() == ""


def test_environment_overrides_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("APP_NAME=From file\nDEBUG=true\n", encoding="utf-8")
    monkeypatch.setenv("APP_NAME", "From environment")
    settings = Settings(_env_file=env_file)
    assert settings.app_name == "From environment"
    assert settings.debug is True


@pytest.mark.parametrize(
    "values",
    [
        {"app_env": "unknown"},
        {"debug": "perhaps"},
        {"app_name": ""},
        {"max_upload_size_mb": 0},
        {"database_url": "invalid"},
    ],
)
def test_invalid_settings(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_secret_is_masked_in_representation() -> None:
    settings = Settings(_env_file=None, openai_api_key="synthetic-test-secret")
    assert "synthetic-test-secret" not in repr(settings)
