"""Compatibility facade retained for earlier callers and tests."""

from app.config import Settings
from app.services.openai_provider import OpenAIProvider


def get_provider(settings: Settings):
    return OpenAIProvider(settings)


def generate_analysis(payload, settings: Settings):
    generated = get_provider(settings).analyze_incident(payload)
    return {
        "result": generated.result.model_dump(mode="json"),
        "provider": generated.provider,
        "model": generated.model,
        "prompt_version": generated.prompt_version,
        "duration_seconds": generated.duration_seconds,
        "usage": {
            "input_tokens": generated.usage.input_tokens,
            "output_tokens": generated.usage.output_tokens,
        },
    }
