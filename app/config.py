"""Typed configuration loaded from the project .env and environment."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Typed settings; database configuration is checked when the app starts."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = Field(default="AI Incident Copilot", min_length=1)
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    jwt_secret_key: SecretStr = SecretStr("")
    jwt_issuer: str = Field(default="incident-copilot", min_length=1)
    jwt_audience: str = Field(default="incident-copilot-api", min_length=1)
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_days: int = Field(default=7, ge=1, le=30)
    allow_registration: bool = False

    def validate_auth_configuration(self) -> None:
        if len(self.jwt_secret_key.get_secret_value().encode("utf-8")) < 32:
            raise RuntimeError(
                "JWT_SECRET_KEY must contain at least 32 bytes. Configure a random private key."
            )
        if self.app_env == "production" and self.debug:
            raise RuntimeError("DEBUG must be false in production.")

    # Retained for compatibility with the earlier database implementation.
    database_url: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = ""
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=60, gt=0, le=300)
    upload_directory: Path = Path("uploads")
    max_upload_size_mb: int = Field(default=5, gt=0)
    max_files_per_incident: int = Field(default=10, ge=1, le=50)
    max_evidence_items: int = Field(default=30, ge=1, le=100)

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        url = value.get_secret_value()
        if url and not url.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use postgresql+psycopg://")
        return value
