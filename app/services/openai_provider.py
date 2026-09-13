"""OpenAI Responses API adapter; no SDK calls exist in business logic."""

import json
from time import monotonic
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, OpenAI, RateLimitError

from app.analysis_schemas import IncidentAnalysis
from app.config import Settings
from app.services.ai_provider import (
    AnswerResult,
    EmbeddingResult,
    ProviderResult,
    ProviderUsage,
    RunbookAnswer,
    TransientProviderError,
)
from app.services.prompt_registry import INCIDENT_ANALYSIS_PROMPT, RUNBOOK_QA_PROMPT, load_prompt


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings):
        self.settings = settings

    def analyze_incident(self, payload: dict[str, Any]) -> ProviderResult:
        model = self.settings.llm_model.strip() or self.settings.openai_model.strip()
        if not self.settings.openai_api_key.get_secret_value() or not model:
            raise ValueError("LLM configuration is missing.")
        serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode("utf-8")) > 200_000:
            raise ValueError("Selected evidence exceeds the provider input budget.")
        prompt = load_prompt(INCIDENT_ANALYSIS_PROMPT)
        started = monotonic()
        try:
            with OpenAI(
                api_key=self.settings.openai_api_key.get_secret_value(),
                timeout=self.settings.llm_timeout_seconds,
                max_retries=0,
            ) as client:
                response = client.responses.parse(
                    model=model,
                    instructions=prompt.instructions,
                    input=serialized,
                    text_format=IncidentAnalysis,
                    max_output_tokens=4000,
                    store=False,
                )
        except (APIConnectionError, APITimeoutError, RateLimitError) as error:
            raise TransientProviderError("Provider temporarily unavailable.") from error
        except APIStatusError as error:
            if error.status_code >= 500:
                raise TransientProviderError("Provider temporarily unavailable.") from error
            raise
        if response.status != "completed" or response.output_parsed is None:
            raise ValueError("Provider did not return a completed structured analysis.")
        usage = response.usage
        return ProviderResult(
            result=response.output_parsed,
            provider=self.name,
            model=model,
            prompt_version=prompt.version,
            duration_seconds=round(monotonic() - started, 3),
            usage=ProviderUsage(
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
            ),
        )

    def answer_runbook_question(self, question: str, context: list[dict[str, Any]]):
        model = self.settings.llm_model.strip() or self.settings.openai_model.strip()
        self._require_configuration(model)
        payload = json.dumps({"question": question, "chunks": context}, ensure_ascii=False)
        instructions = load_prompt(RUNBOOK_QA_PROMPT).instructions
        started = monotonic()
        try:
            with self._client() as client:
                response = client.responses.parse(
                    model=model,
                    instructions=instructions,
                    input=payload,
                    text_format=RunbookAnswer,
                    max_output_tokens=2500,
                    store=False,
                )
        except (APIConnectionError, APITimeoutError, RateLimitError) as error:
            raise TransientProviderError("Provider temporarily unavailable.") from error
        if response.status != "completed" or response.output_parsed is None:
            raise ValueError("Provider did not return a completed runbook answer.")
        return AnswerResult(
            result=response.output_parsed,
            provider=self.name,
            model=model,
            duration_seconds=round(monotonic() - started, 3),
            usage=self._usage(response.usage),
        )

    def create_embeddings(self, texts: list[str]):
        if not texts:
            raise ValueError("At least one embedding input is required.")
        model = self.settings.embedding_model.strip()
        self._require_configuration(model)
        started = monotonic()
        try:
            with self._client() as client:
                response = client.embeddings.create(
                    model=model,
                    input=texts,
                    dimensions=self.settings.embedding_dimensions,
                    encoding_format="float",
                )
        except (APIConnectionError, APITimeoutError, RateLimitError) as error:
            raise TransientProviderError("Provider temporarily unavailable.") from error
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        return EmbeddingResult(
            vectors=vectors,
            provider=self.name,
            model=model,
            duration_seconds=round(monotonic() - started, 3),
            usage=ProviderUsage(input_tokens=getattr(response.usage, "prompt_tokens", None)),
        )

    def _require_configuration(self, model):
        if not self.settings.openai_api_key.get_secret_value() or not model:
            raise ValueError("Provider configuration is missing.")

    def _client(self):
        return OpenAI(
            api_key=self.settings.openai_api_key.get_secret_value(),
            timeout=self.settings.llm_timeout_seconds,
            max_retries=0,
        )

    @staticmethod
    def _usage(usage):
        return ProviderUsage(
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )
