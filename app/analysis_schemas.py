"""Strict structured-analysis contract and evidence-reference validation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Observation(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[str] = Field(min_length=1)


class PossibleCause(StrictModel):
    cause: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    evidence_ids: list[str] = Field(min_length=1)


class RecommendedCheck(StrictModel):
    order: int = Field(ge=1)
    action: str = Field(min_length=1, max_length=1000)
    command: str | None = Field(max_length=2000)
    risk: Literal["READ_ONLY", "CHANGES_SYSTEM", "UNKNOWN"]


class IncidentAnalysis(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    incident_type: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=4000)
    affected_components: list[str] = Field(max_length=50)
    observations: list[Observation]
    possible_causes: list[PossibleCause]
    recommended_checks: list[RecommendedCheck]
    information_gaps: list[str] = Field(max_length=50)
    suggested_escalation_team: str | None = Field(max_length=200)

    @field_validator("affected_components", "information_gaps")
    @classmethod
    def nonempty_unique_strings(cls, values):
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 1000 for value in cleaned):
            raise ValueError("List values must be nonempty and bounded.")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("List values must be unique.")
        return cleaned

    @model_validator(mode="after")
    def ordered_checks(self):
        orders = [item.order for item in self.recommended_checks]
        if orders != list(range(1, len(orders) + 1)):
            raise ValueError("Recommended checks must use consecutive unique order values.")
        return self


def validate_evidence_references(analysis: IncidentAnalysis, evidence_ids: set[str]) -> None:
    for item in [*analysis.observations, *analysis.possible_causes]:
        if len(item.evidence_ids) != len(set(item.evidence_ids)):
            raise ValueError("Analysis contains duplicate evidence references.")
        if not set(item.evidence_ids) <= evidence_ids:
            raise ValueError("Analysis cites unknown evidence.")
