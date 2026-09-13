"""Runbook chunks and incident vectors used by exact similarity search."""

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import CreatedMixin, IdentityMixin, utc_now

EMBEDDING_DIMENSIONS = 1536
EMBEDDING_TYPE = Vector(EMBEDDING_DIMENSIONS).with_variant(JSON(), "sqlite")


class Runbook(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "runbooks"

    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    is_global: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str] = mapped_column(Text)
    storage_scope: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(30), default="PENDING", server_default="PENDING", index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )


class RunbookChunk(IdentityMixin, Base):
    __tablename__ = "runbook_chunks"
    __table_args__ = (UniqueConstraint("runbook_id", "chunk_index", name="uq_runbook_chunk"),)

    runbook_id: Mapped[str] = mapped_column(
        ForeignKey("runbooks.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_name: Mapped[str | None] = mapped_column(String(300))
    embedding: Mapped[list[float]] = mapped_column(EMBEDDING_TYPE)
    chunk_metadata: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)


class IncidentEmbedding(Base):
    __tablename__ = "incident_embeddings"

    incident_id: Mapped[str] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), primary_key=True
    )
    searchable_summary: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(EMBEDDING_TYPE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, server_default=text("CURRENT_TIMESTAMP")
    )
