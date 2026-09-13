"""Provider interface and immutable prompt registry contracts."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from openai import APITimeoutError

from app.analysis_schemas import IncidentAnalysis
from app.services.ai_provider import (
    AIProvider,
    ProviderResult,
    ProviderUsage,
    TransientProviderError,
)
from app.services.openai_provider import OpenAIProvider
from app.services.prompt_registry import INCIDENT_ANALYSIS_PROMPT, RUNBOOK_QA_PROMPT, load_prompt


def test_openai_adapter_satisfies_provider_protocol() -> None:
    assert hasattr(OpenAIProvider, "analyze_incident")
    assert set(AIProvider.__dict__) >= {
        "analyze_incident",
        "answer_runbook_question",
        "create_embeddings",
    }


def test_prompt_registry_is_allowlisted_and_rejects_missing_or_empty(tmp_path: Path) -> None:
    prompt = load_prompt(INCIDENT_ANALYSIS_PROMPT)
    assert prompt.version == INCIDENT_ANALYSIS_PROMPT
    assert "untrusted data" in prompt.instructions
    assert "untrusted data" in load_prompt(RUNBOOK_QA_PROMPT).instructions
    with pytest.raises(ValueError, match="Unknown prompt"):
        load_prompt("../../private")
    (tmp_path / "incident_analysis_v1.txt").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_prompt(INCIDENT_ANALYSIS_PROMPT, tmp_path)


def test_provider_result_is_typed_and_immutable() -> None:
    analysis = IncidentAnalysis.model_validate(
        {
            "title": "Synthetic",
            "severity": "LOW",
            "incident_type": "TEST",
            "summary": "Synthetic result",
            "affected_components": [],
            "observations": [],
            "possible_causes": [],
            "recommended_checks": [],
            "information_gaps": [],
            "suggested_escalation_team": None,
        }
    )
    generated = ProviderResult(
        result=analysis,
        provider="mock",
        model="mock-model",
        prompt_version="test_v1",
        duration_seconds=0.1,
        usage=ProviderUsage(10, 4),
    )
    with pytest.raises(AttributeError):
        generated.provider = "changed"


def test_adapter_translates_transient_sdk_failure(monkeypatch) -> None:
    from app.config import Settings

    constructor = MagicMock()
    constructor.return_value.__enter__.return_value.responses.parse.side_effect = APITimeoutError(
        request=MagicMock()
    )
    monkeypatch.setattr("app.services.openai_provider.OpenAI", constructor)
    provider = OpenAIProvider(
        Settings(_env_file=None, openai_api_key="synthetic-key", llm_model="test-model")
    )
    with pytest.raises(TransientProviderError) as error:
        provider.analyze_incident({"statistics": {}, "evidence": []})
    assert "synthetic-key" not in str(error.value)


def test_embedding_adapter_batches_inputs_and_maps_usage(monkeypatch) -> None:
    from app.config import Settings

    constructor = MagicMock()
    response = MagicMock()
    response.data = [
        MagicMock(index=1, embedding=[0.0] * 1536),
        MagicMock(index=0, embedding=[1.0] * 1536),
    ]
    response.usage.prompt_tokens = 12
    constructor.return_value.__enter__.return_value.embeddings.create.return_value = response
    monkeypatch.setattr("app.services.openai_provider.OpenAI", constructor)
    provider = OpenAIProvider(Settings(_env_file=None, openai_api_key="synthetic-key"))

    result = provider.create_embeddings(["first", "second"])

    assert result.vectors[0][0] == 1.0
    assert result.usage.input_tokens == 12
    call = constructor.return_value.__enter__.return_value.embeddings.create.call_args.kwargs
    assert call["model"] == "text-embedding-3-small"
    assert call["dimensions"] == 1536
    assert call["encoding_format"] == "float"


def test_runbook_answer_adapter_uses_structured_response_without_storage(monkeypatch) -> None:
    from app.config import Settings
    from app.services.ai_provider import RunbookAnswer

    constructor = MagicMock()
    response = MagicMock(
        status="completed",
        output_parsed=RunbookAnswer(
            answer="Synthetic answer",
            citations=[{"chunk_id": "chunk-1"}],
            insufficient_context=False,
        ),
    )
    response.usage.input_tokens = 10
    response.usage.output_tokens = 4
    constructor.return_value.__enter__.return_value.responses.parse.return_value = response
    monkeypatch.setattr("app.services.openai_provider.OpenAI", constructor)
    provider = OpenAIProvider(
        Settings(_env_file=None, openai_api_key="synthetic-key", llm_model="test-model")
    )

    result = provider.answer_runbook_question(
        "Synthetic question", [{"chunk_id": "chunk-1", "text": "Synthetic context"}]
    )

    assert result.result.answer == "Synthetic answer"
    call = constructor.return_value.__enter__.return_value.responses.parse.call_args.kwargs
    assert call["store"] is False
    assert call["text_format"] is RunbookAnswer
    assert "untrusted data" in call["instructions"]
