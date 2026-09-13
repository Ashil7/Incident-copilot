"""Normalized storage for later file and worker workflows."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import CreatedMixin, IdentityMixin, utc_now


class LogFile(IdentityMixin, Base):
    __tablename__ = "log_files"
    __table_args__ = (CheckConstraint("size_bytes >= 0", name="ck_log_files_size"),)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    original_filename: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    storage_scope: Mapped[str | None] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LogEvent(IdentityMixin, Base):
    __tablename__ = "log_events"
    __table_args__ = (
        CheckConstraint("source_line_number > 0", name="ck_log_events_line"),
        UniqueConstraint("log_file_id", "source_line_number", name="uq_log_events_file_line"),
    )
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    log_file_id: Mapped[str] = mapped_column(ForeignKey("log_files.id"), index=True)
    source_line_number: Mapped[int] = mapped_column(Integer)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    level: Mapped[str] = mapped_column(String(20), index=True)
    service: Mapped[str | None] = mapped_column(String(200))
    http_method: Mapped[str | None] = mapped_column(String(20))
    endpoint: Mapped[str | None] = mapped_column(Text, index=True)
    status_code: Mapped[int | None] = mapped_column(Integer, index=True)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    trace_id: Mapped[str | None] = mapped_column(Text)
    error_signature: Mapped[str | None] = mapped_column(Text)
    redacted_message: Mapped[str] = mapped_column(Text)
    is_evidence: Mapped[bool] = mapped_column(Boolean, default=False)


class StorageDeletion(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "storage_deletions"
    storage_key: Mapped[str] = mapped_column(Text, unique=True)
    storage_scope: Mapped[str] = mapped_column(String(64))


class AnalysisJob(IdentityMixin, Base):
    __tablename__ = "analysis_jobs"
    __table_args__ = (
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_analysis_jobs_progress"),
        CheckConstraint("attempt_count >= 0", name="ck_analysis_jobs_attempts"),
        Index(
            "uq_analysis_jobs_active",
            "incident_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'RUNNING', 'RETRY')"),
            sqlite_where=text("status IN ('PENDING', 'RUNNING', 'RETRY')"),
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
    request_id: Mapped[str | None] = mapped_column(String(36))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    analyze: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    cleanup: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    current_stage: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IncidentAnalysis(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "incident_analyses"
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(200))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
