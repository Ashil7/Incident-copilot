"""Public incident response; internal storage paths are intentionally omitted."""

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import Environment, IncidentStatus


class IncidentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str = Field(min_length=1, max_length=200)
    owner_user_id: str | None
    severity: str | None
    service_name: str | None
    environment: Environment
    status: IncidentStatus
    original_filename: str | None
    statistics: dict[str, Any] | None
    analysis: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None

    @field_validator("created_at", "completed_at")
    @classmethod
    def normalize_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        """Application timestamps are UTC; SQLite reads lose their timezone metadata."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class LogFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    incident_id: str
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    uploaded_at: datetime

    @field_validator("uploaded_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime) -> datetime:
        return IncidentResponse.normalize_utc_timestamp(value)
