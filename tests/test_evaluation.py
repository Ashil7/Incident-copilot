import json
import sys

import pytest

from app.analysis_schemas import IncidentAnalysis
from app.config import PROJECT_ROOT
from app.evaluation import evaluate, evaluate_case, load_dataset
from app.services.ai_provider import ProviderResult, ProviderUsage
from scripts import evaluate_ai

DATASET = PROJECT_ROOT / "evaluations" / "incident_analysis.json"


class FixtureProvider:
    def __init__(self, cases):
        self.results = iter(case.fixture_analysis for case in cases)

    def analyze_incident(self, payload):
        assert "statistics" in payload and "evidence" in payload
        return ProviderResult(
            result=next(self.results),
            provider="mock",
            model="mock-model",
            prompt_version="test",
            duration_seconds=0.125,
            usage=ProviderUsage(input_tokens=40, output_tokens=20),
        )

    def answer_runbook_question(self, question, context):
        raise NotImplementedError

    def create_embeddings(self, texts):
        raise NotImplementedError


def test_offline_dataset_scores_expected_metrics_without_sensitive_report_data():
    cases = load_dataset(DATASET)

    report = evaluate(cases)
    serialized = json.dumps(report)

    assert len(cases) == 3
    assert report["mode"] == "offline"
    assert report["metrics"] == {
        "parser_success_rate": 1.0,
        "field_accuracy": 1.0,
        "redaction_recall": 1.0,
        "statistics_accuracy": 1.0,
        "unsupported_claim_rate": 0.0,
        "information_gap_recall": 1.0,
        "evidence_reference_validity": 1.0,
        "incident_type_agreement": 1.0,
    }
    assert "synthetic-secret" not in serialized
    assert "synthetic-token" not in serialized
    assert all(case["latency_seconds"] is None for case in report["cases"])


def test_mock_provider_adds_measured_usage_and_latency():
    cases = load_dataset(DATASET)

    report = evaluate(cases, FixtureProvider(cases))

    assert report["mode"] == "live"
    assert all(case["latency_seconds"] == 0.125 for case in report["cases"])
    assert all(case["input_tokens"] == 40 for case in report["cases"])
    assert all(case["output_tokens"] == 20 for case in report["cases"])


def test_invalid_evidence_reference_and_unsupported_claim_are_measured():
    case = load_dataset(DATASET)[1]
    invalid = IncidentAnalysis.model_validate(
        {
            **case.fixture_analysis.model_dump(),
            "observations": [{"text": "An unsupported assertion.", "evidence_ids": ["E99"]}],
            "possible_causes": [],
        }
    )
    changed = case.model_copy(update={"fixture_analysis": invalid})

    score = evaluate_case(changed)

    assert score.evidence_references_valid is False
    assert score.unsupported_claim_rate == 1.0


def test_cli_offline_does_not_construct_provider(monkeypatch, tmp_path, capsys):
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        evaluate_ai, "get_provider", lambda settings: pytest.fail("provider constructed")
    )
    monkeypatch.setattr(sys, "argv", ["evaluate_ai", "--output", str(output)])

    evaluate_ai.main()

    assert json.loads(output.read_text(encoding="utf-8"))["mode"] == "offline"
    assert "PASS: offline evaluation" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--live", "--confirm-cost"])
def test_cli_requires_both_live_flags(monkeypatch, flag):
    monkeypatch.setattr(sys, "argv", ["evaluate_ai", flag])

    with pytest.raises(SystemExit) as error:
        evaluate_ai.main()

    assert error.value.code == 2


def test_dataset_rejects_duplicate_ids(tmp_path):
    case = json.loads(DATASET.read_text(encoding="utf-8"))[0]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps([case, case]), encoding="utf-8")

    with pytest.raises(ValueError, match="nonempty and unique"):
        load_dataset(path)
