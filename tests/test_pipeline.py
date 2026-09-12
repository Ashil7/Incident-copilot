"""Mocked provider, real offline sessions, and full background task integration."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import Session

from app.analysis_schemas import IncidentAnalysis, validate_evidence_references
from app.config import Settings
from app.services import llm_service, pipeline


@pytest.fixture(autouse=True)
def authenticate_pipeline_requests(incident_user):
    pass


def result(evidence_id: str = "E1") -> dict:
    return {
        "title": "Synthetic incident",
        "severity": "HIGH",
        "incident_type": "HTTP_FAILURE",
        "summary": "A request failed; the cause is unknown.",
        "affected_components": [],
        "observations": [{"text": "A failure occurred.", "evidence_ids": [evidence_id]}],
        "possible_causes": [
            {
                "cause": "An upstream issue is possible.",
                "confidence": 0.5,
                "evidence_ids": [evidence_id],
            }
        ],
        "recommended_checks": [
            {
                "order": 1,
                "action": "Review synthetic dependency health",
                "command": None,
                "risk": "READ_ONLY",
            }
        ],
        "information_gaps": ["Dependency metrics are not available."],
        "suggested_escalation_team": None,
    }


def post(client: TestClient, body: bytes = b"ERROR GET /api 500 25ms password=synthetic-secret"):
    return client.post(
        "/api/v1/incidents",
        data={"title": "Synthetic"},
        files={"log_file": ("test.log", body, "text/plain")},
    )


def test_background_success_redaction_and_transitions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    states = []

    def committed(session: Session) -> None:
        from app.models import Incident

        states.extend(
            item.status.value
            for item in session.identity_map.values()
            if isinstance(item, Incident)
        )

    sqlalchemy_event.listen(Session, "after_commit", committed)
    captured = []

    def fake(payload, settings):
        captured.append(payload)
        return {"result": result(payload["evidence"][0]["evidence_id"]), "provider": "mock"}

    monkeypatch.setattr(pipeline, "generate_analysis", fake)
    try:
        response = post(client)
    finally:
        sqlalchemy_event.remove(Session, "after_commit", committed)
    assert response.status_code == 202
    assert response.json()["status"] == "UPLOADED"
    detail = client.get(f"/api/v1/incidents/{response.json()['id']}").json()
    assert detail["status"] == "COMPLETED"
    assert detail["completed_at"] is not None
    assert detail["analysis"]["result"]["severity"] == "HIGH"
    assert detail["statistics"]["error_count"] == 1
    assert "synthetic-secret" not in json.dumps(captured)
    assert "synthetic-secret" not in json.dumps(detail)
    assert set(captured[0]) == {"statistics", "evidence"}
    assert {"CALCULATING", "GENERATING_ANALYSIS", "VALIDATING", "COMPLETED"} <= set(states)
    pipeline.run_analysis(
        response.json()["id"], client.app.state.session_factory, client.app.state.settings
    )
    assert len(captured) == 1  # A terminal incident cannot be claimed twice.


@pytest.mark.parametrize("failure", ["exception", "unknown_id", "invalid_schema"])
def test_failure_is_safe_and_statistics_survive(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def fake(payload, settings):
        if failure == "exception":
            raise RuntimeError("private-provider-secret")
        return {
            "result": result("E999")
            if failure == "unknown_id"
            else {"bad": "private-provider-secret"}
        }

    monkeypatch.setattr(pipeline, "generate_analysis", fake)
    response = post(client)
    assert response.status_code == 202
    detail = client.get(f"/api/v1/incidents/{response.json()['id']}").json()
    assert detail["status"] == "FAILED"
    assert detail["analysis"] is None
    assert detail["statistics"]["evidence"]
    assert "private-provider-secret" not in json.dumps(detail)
    assert client.get("/health").status_code == 200


def test_missing_config_is_controlled_failure(client: TestClient) -> None:
    response = post(client)
    assert client.get(f"/api/v1/incidents/{response.json()['id']}").json()["status"] == "FAILED"


def test_missing_upload_records_safe_failure(client: TestClient, monkeypatch) -> None:
    from app.services.incident_files import file_rows
    from app.services.storage import get_storage

    monkeypatch.setattr("app.routers.incidents.run_analysis", lambda *args: None)
    response = post(client)
    incident_id = response.json()["id"]
    with client.app.state.session_factory() as session:
        row = file_rows(session, incident_id)[0]
        get_storage(client.app.state.settings).delete(row.storage_key)
    provider = MagicMock(side_effect=AssertionError("Must not call provider"))
    monkeypatch.setattr(pipeline, "generate_analysis", provider)
    pipeline.run_analysis(incident_id, client.app.state.session_factory, client.app.state.settings)
    detail = client.get(f"/api/v1/incidents/{incident_id}").json()
    assert detail["status"] == "FAILED"
    assert detail["completed_at"] is not None
    assert detail["analysis"] is None
    assert "missing.log" not in detail["error_message"]
    provider.assert_not_called()


def test_provider_output_is_redacted(client: TestClient, monkeypatch) -> None:
    data = result()
    data["summary"] = "password=synthetic-output-secret"
    monkeypatch.setattr(pipeline, "generate_analysis", lambda *args: {"result": data})
    response = post(client)
    detail = client.get(f"/api/v1/incidents/{response.json()['id']}").json()
    assert detail["status"] == "COMPLETED"
    assert "synthetic-output-secret" not in json.dumps(detail)


def test_healthy_log_skips_provider(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    provider = MagicMock(side_effect=AssertionError("Must not call provider"))
    monkeypatch.setattr(pipeline, "generate_analysis", provider)
    response = post(client, b"INFO GET /health 200 10ms")
    detail = client.get(f"/api/v1/incidents/{response.json()['id']}").json()
    assert detail["status"] == "COMPLETED"
    assert detail["analysis"]["provider"] == "deterministic"
    provider.assert_not_called()


def test_schema_rejects_confidence_and_empty_citations() -> None:
    data = result()
    data["possible_causes"][0]["confidence"] = 1.5
    with pytest.raises(ValidationError):
        IncidentAnalysis.model_validate(data)
    data = result()
    data["observations"][0]["evidence_ids"] = []
    with pytest.raises(ValidationError):
        IncidentAnalysis.model_validate(data)
    with pytest.raises(ValueError):
        validate_evidence_references(IncidentAnalysis.model_validate(result()), {"E2"})


@pytest.mark.parametrize("completed", [True, False])
def test_sdk_adapter_contract(monkeypatch: pytest.MonkeyPatch, completed: bool) -> None:
    constructor = MagicMock()
    client = constructor.return_value.__enter__.return_value
    response = client.responses.parse.return_value
    response.status = "completed" if completed else "incomplete"
    response.output_parsed = IncidentAnalysis.model_validate(result()) if completed else None
    response.usage = None
    monkeypatch.setattr(llm_service, "OpenAI", constructor)
    settings = Settings(_env_file=None, openai_api_key="fake-test-key", llm_model="test-model")
    payload = {"statistics": {"error_count": 1}, "evidence": []}
    if completed:
        assert llm_service.generate_analysis(payload, settings)["model"] == "test-model"
    else:
        with pytest.raises(ValueError):
            llm_service.generate_analysis(payload, settings)
    kwargs = client.responses.parse.call_args.kwargs
    assert kwargs["text_format"] is IncidentAnalysis
    assert kwargs["store"] is False
    assert "tools" not in kwargs
    assert "untrusted data" in kwargs["instructions"]
    assert json.loads(kwargs["input"]) == payload
