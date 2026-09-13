"""Provider-neutral AI contracts used by analysis and future retrieval features."""

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.analysis_schemas import IncidentAnalysis


class TransientProviderError(Exception):
    """Safe provider-neutral signal for a controlled durable retry."""


@dataclass(frozen=True)
class ProviderUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class ProviderResult:
    result: IncidentAnalysis
    provider: str
    model: str | None
    prompt_version: str | None
    duration_seconds: float
    usage: ProviderUsage


class RunbookCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str


class RunbookAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str = Field(min_length=1, max_length=6000)
    citations: list[RunbookCitation]
    insufficient_context: bool


@dataclass(frozen=True)
class AnswerResult:
    result: RunbookAnswer
    provider: str
    model: str
    duration_seconds: float
    usage: ProviderUsage


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    provider: str
    model: str
    duration_seconds: float
    usage: ProviderUsage


class AIProvider(Protocol):
    def analyze_incident(self, payload: dict[str, Any]) -> ProviderResult: ...

    def answer_runbook_question(
        self, question: str, context: list[dict[str, Any]]
    ) -> AnswerResult: ...

    def create_embeddings(self, texts: list[str]) -> EmbeddingResult: ...
