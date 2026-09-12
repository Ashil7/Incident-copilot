"""Feedback and safe audit records; routes are deferred to later milestones."""

from typing import Any

from sqlalchemy import JSON, Boolean, CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.common import CreatedMixin, IdentityMixin


class Feedback(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating"),)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    helpful: Mapped[bool] = mapped_column(Boolean)
    rating: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    corrected_incident_type: Mapped[str | None] = mapped_column(String(100))


class AuditEvent(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "audit_events"
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(36), index=True)
    request_id: Mapped[str | None] = mapped_column(String(100))
    safe_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
