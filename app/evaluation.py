"""Deterministic evaluation runner for synthetic incident-analysis cases."""

import json
from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path
from time import monotonic
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.analysis_schemas import IncidentAnalysis, validate_evidence_references
from app.services.ai_provider import AIProvider
from app.services.error_signatures import with_error_signatures
from app.services.evidence_selector import select_evidence
from app.services.log_parser import parse_lines
from app.services.statistics import calculate_statistics


class ExpectedField(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_number: int = Field(gt=0)
    level: str | None = None
    endpoint: str | None = None
    status_code: int | None = None


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    log: str
    secrets: list[str]
    expected_fields: list[ExpectedField]
    expected_statistics: dict[str, Any]
    expected_incident_type: str
    required_information_gaps: list[str]
    supported_claims: list[str]
    fixture_analysis: IncidentAnalysis


@dataclass(frozen=True)
class CaseScore:
    id: str
    parser_success_rate: float
    field_accuracy: float
    redaction_recall: float
    statistics_accuracy: float
    evidence_references_valid: bool
    incident_type_agreement: bool
    unsupported_claim_rate: float
    information_gap_recall: float
    latency_seconds: float | None
    input_tokens: int | None
    output_tokens: int | None


def load_dataset(path: Path) -> list[EvalCase]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = [EvalCase.model_validate(item) for item in data]
    ids = [item.id for item in cases]
    if not cases or len(ids) != len(set(ids)):
        raise ValueError("Evaluation case IDs must be nonempty and unique.")
    return cases


def ratio(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 1.0


def evaluate_case(case: EvalCase, provider: AIProvider | None = None) -> CaseScore:
    parsed = parse_lines(StringIO(case.log), mask_ipv4=True)
    events = with_error_signatures(parsed.events)
    statistics = calculate_statistics(parsed)
    evidence = select_evidence(events)
    payload = {
        "statistics": statistics,
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }
    started = monotonic()
    generated = provider.analyze_incident(payload) if provider else None
    elapsed = round(monotonic() - started, 3) if provider else None
    analysis = generated.result if generated else case.fixture_analysis
    evidence_ids = {item.evidence_id for item in evidence}
    references_valid = True
    try:
        validate_evidence_references(analysis, evidence_ids)
    except ValueError:
        references_valid = False

    by_line = {event.line_number: event for event in events}
    matched = 0
    total_fields = 0
    for expected in case.expected_fields:
        event = by_line.get(expected.line_number)
        for field in ("level", "endpoint", "status_code"):
            value = getattr(expected, field)
            if value is not None:
                total_fields += 1
                matched += bool(event and getattr(event, field) == value)
    stat_matches = sum(
        statistics.get(key) == value for key, value in case.expected_statistics.items()
    )
    messages = "\n".join(event.message for event in events)
    claim_texts = [item.text for item in analysis.observations] + [
        item.cause for item in analysis.possible_causes
    ]
    unsupported = sum(text not in case.supported_claims for text in claim_texts)
    gaps = {value.casefold() for value in analysis.information_gaps}
    required = {value.casefold() for value in case.required_information_gaps}
    return CaseScore(
        id=case.id,
        parser_success_rate=ratio(
            parsed.parsed + parsed.partial, parsed.total_lines - parsed.blank
        ),
        field_accuracy=ratio(matched, total_fields),
        redaction_recall=ratio(
            sum(secret not in messages for secret in case.secrets), len(case.secrets)
        ),
        statistics_accuracy=ratio(stat_matches, len(case.expected_statistics)),
        evidence_references_valid=references_valid,
        incident_type_agreement=analysis.incident_type == case.expected_incident_type,
        unsupported_claim_rate=(round(unsupported / len(claim_texts), 4) if claim_texts else 0.0),
        information_gap_recall=ratio(len(required & gaps), len(required)),
        latency_seconds=(generated.duration_seconds if generated else elapsed),
        input_tokens=(generated.usage.input_tokens if generated else None),
        output_tokens=(generated.usage.output_tokens if generated else None),
    )


def evaluate(cases: list[EvalCase], provider: AIProvider | None = None) -> dict[str, Any]:
    scores = [evaluate_case(case, provider) for case in cases]
    metrics = {}
    for field in (
        "parser_success_rate",
        "field_accuracy",
        "redaction_recall",
        "statistics_accuracy",
        "unsupported_claim_rate",
        "information_gap_recall",
    ):
        metrics[field] = round(sum(getattr(score, field) for score in scores) / len(scores), 4)
    metrics["evidence_reference_validity"] = ratio(
        sum(score.evidence_references_valid for score in scores), len(scores)
    )
    metrics["incident_type_agreement"] = ratio(
        sum(score.incident_type_agreement for score in scores), len(scores)
    )
    return {
        "mode": "live" if provider else "offline",
        "case_count": len(scores),
        "metrics": metrics,
        "cases": [asdict(score) for score in scores],
    }
