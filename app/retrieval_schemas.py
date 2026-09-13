"""Public contracts for runbooks, retrieval answers, similarity, and feedback."""

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RunbookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    title: str
    description: str | None
    original_filename: str
    is_global: bool
    status: str
    error_message: str | None
    created_at: datetime
    indexed_at: datetime | None

    @field_validator("created_at", "indexed_at")
    @classmethod
    def utc(cls, value):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class CitationResponse(BaseModel):
    runbook_id: str
    runbook_title: str
    chunk_id: str
    page_number: int | None
    section_name: str | None
    excerpt: str


class RunbookAskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    runbook_ids: list[str] | None = Field(default=None, max_length=50)


class RunbookAskResponse(BaseModel):
    answer: str
    insufficient_context: bool
    citations: list[CitationResponse]


class ResolutionUpdate(BaseModel):
    confirmed_root_cause: str = Field(min_length=1, max_length=4000)
    resolution_notes: str = Field(min_length=1, max_length=8000)
    severity: str | None = Field(default=None, pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$")


class FeedbackCreate(BaseModel):
    helpful: bool
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)
    corrected_incident_type: str | None = Field(default=None, max_length=100)


class FeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    incident_id: str
    helpful: bool
    rating: int | None
    comment: str | None
    corrected_incident_type: str | None
    created_at: datetime


class SimilarIncidentResponse(BaseModel):
    incident_id: str
    title: str
    similarity: str
    confirmed_resolution: str | None
    incident_type: str | None
