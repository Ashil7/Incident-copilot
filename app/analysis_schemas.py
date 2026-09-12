"""Strict structured-analysis contract and evidence-reference validation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(StrictModel):
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class PossibleCause(StrictModel):
    cause: str
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_ids: list[str] = Field(min_length=1)


class RecommendedCheck(StrictModel):
    order: int = Field(ge=1)
    action: str
    command: str | None
    risk: Literal["READ_ONLY", "CHANGES_SYSTEM", "UNKNOWN"]


class IncidentAnalysis(StrictModel):
    title: str
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    incident_type: str
    summary: str
    affected_components: list[str]
    observations: list[Observation]
    possible_causes: list[PossibleCause]
    recommended_checks: list[RecommendedCheck]
    information_gaps: list[str]
    suggested_escalation_team: str | None


def validate_evidence_references(analysis: IncidentAnalysis, evidence_ids: set[str]) -> None:
    for item in [*analysis.observations, *analysis.possible_causes]:
        if not set(item.evidence_ids) <= evidence_ids:
            raise ValueError("Analysis cites unknown evidence.")
