"""Stable grouping of already-redacted errors; grouping is not root-cause diagnosis."""

import re

from app.services.log_parser import TIMESTAMP, LogEvent

UUID = re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.I)
NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
DURATION = re.compile(r"\b\d+(?:\.\d+)?\s*(?:milliseconds|seconds|ms|s)\b", re.I)


def is_error(event: LogEvent) -> bool:
    return event.level in {"ERROR", "CRITICAL", "FATAL"} or (
        event.status_code is not None and event.status_code >= 400
    )


def error_signature(event: LogEvent) -> str:
    """Normalize timestamps, UUIDs and variable numbers while retaining HTTP status."""
    message = TIMESTAMP.sub("", event.message)
    message = UUID.sub("<id>", message)
    message = DURATION.sub("<duration>", message)
    message = NUMBER.sub("<n>", message)
    message = " ".join(message.lower().split())
    return f"{event.level or 'UNKNOWN'}|{event.status_code or '-'}|{message}"


def with_error_signatures(events: list[LogEvent]) -> list[LogEvent]:
    """Return enriched copies so the parser's output is not mutated."""
    return [
        event.model_copy(
            update={"error_signature": error_signature(event) if is_error(event) else None}
        )
        for event in events
    ]
