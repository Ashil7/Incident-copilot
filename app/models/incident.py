"""Incident storage and its allowed environment and processing states."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import UpdatedMixin


class Environment(StrEnum):
    DEV = "DEV"
    UAT = "UAT"
    PROD = "PROD"


class IncidentStatus(StrEnum):
    CREATED = "CREATED"
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    CALCULATING = "CALCULATING"
    GENERATING_ANALYSIS = "GENERATING_ANALYSIS"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class Incident(UpdatedMixin, Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Nullable during the pre-authentication transition; never fabricate ownership.
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(String(20))
    confirmed_root_cause: Mapped[str | None] = mapped_column(Text)
    resolution_notes: Mapped[str | None] = mapped_column(Text)
    incident_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_name: Mapped[str | None] = mapped_column(String(200))
    environment: Mapped[Environment] = mapped_column(
        Enum(Environment, name="incident_environment", validate_strings=True),
        default=Environment.DEV,
    )
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, name="incident_status", validate_strings=True),
        default=IncidentStatus.CREATED,
        index=True,
    )
    original_filename: Mapped[str | None] = mapped_column(Text)
    stored_file_path: Mapped[str | None] = mapped_column(Text)
    statistics: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    analysis: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
