"""All OpenAI SDK calls live here; callers provide only redacted statistics/evidence."""

import json
from time import monotonic
from typing import Any

from openai import OpenAI

from app.analysis_schemas import IncidentAnalysis
from app.config import PROJECT_ROOT, Settings

PROMPT_VERSION = "incident_analysis_v1"


def generate_analysis(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    model = settings.llm_model.strip() or settings.openai_model.strip()
    if not settings.openai_api_key.get_secret_value() or not model:
        raise ValueError("LLM configuration is missing.")
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(serialized.encode("utf-8")) > 200_000:
        raise ValueError("Selected evidence exceeds the provider input budget.")
    instructions = (PROJECT_ROOT / "app" / "prompts" / f"{PROMPT_VERSION}.txt").read_text(
        encoding="utf-8"
    )
    started = monotonic()
    with OpenAI(
        api_key=settings.openai_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=2,
    ) as client:
        response = client.responses.parse(
            model=model,
            instructions=instructions,
            input=serialized,
            text_format=IncidentAnalysis,
            max_output_tokens=4000,
            store=False,
        )
    if response.status != "completed" or response.output_parsed is None:
        raise ValueError("Provider did not return a completed structured analysis.")
    return {
        "result": response.output_parsed.model_dump(mode="json"),
        "provider": "openai",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "duration_seconds": round(monotonic() - started, 3),
        "usage": response.usage.model_dump(mode="json") if response.usage else None,
    }
