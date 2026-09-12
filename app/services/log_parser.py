"""Standalone redaction and parsing with explicit formats and line accounting."""

import json
import math
import re
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.redactor import MASK, redact_json, redact_text

TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
)
LEVEL = re.compile(r"\b(TRACE|DEBUG|INFO|WARN(?:ING)?|ERROR|CRITICAL|FATAL)\b", re.I)
REQUEST = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[^\s\"]*)", re.I)
STATUS = re.compile(r"\b(?:status_code|status)\s*[=:]\s*(\d{3})\b", re.I)
LATENCY = re.compile(r"(?<![\w.-])(\d+(?:\.\d+)?)\s*(ms|milliseconds|s|seconds)\b", re.I)
SERVICE = re.compile(r"\b(?:service_name|service)\s*[=:]\s*([^\s,;]+)", re.I)
TRACE = re.compile(r"\b(?:trace[_-]?id|correlation[_-]?id)\s*[:=]", re.I)


class LogEvent(BaseModel):
    line_number: int
    source_file_id: str | None = None
    source_line_number: int | None = None
    timestamp: datetime | None = None
    level: str | None = None
    service: str | None = None
    method: str | None = None
    endpoint: str | None = None
    status_code: int | None = None
    latency_ms: float | None = None
    trace_id: str | None = None
    message: str
    error_signature: str | None = None
    parse_status: Literal["parsed", "partial", "unparsed"] = "unparsed"


class ParseResult(BaseModel):
    events: list[LogEvent] = Field(default_factory=list)
    total_lines: int = 0
    parsed: int = 0
    partial: int = 0
    blank: int = 0
    unparsed: int = 0


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace(",", ".").replace("Z", "+00:00"))
    except ValueError:
        return None


def first(data: dict[str, Any], *names: str) -> Any:
    return next((data[name] for name in names if data.get(name) is not None), None)


def string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def latency(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError, OverflowError):
        return None


def status_code(value: Any) -> int | None:
    if isinstance(value, bool) or not re.fullmatch(r"\d{3}", str(value)):
        return None
    number = int(value)
    return number if 100 <= number <= 599 else None


def normalize_level(value: Any) -> str | None:
    if not isinstance(value, str) or not LEVEL.fullmatch(value):
        return None
    return {"WARN": "WARNING", "FATAL": "CRITICAL"}.get(value.upper(), value.upper())


def classify(event: LogEvent) -> LogEvent:
    # Parsed means timestamp + level are recognized; other fields remain optional.
    if event.timestamp is not None and event.level is not None:
        event.parse_status = "parsed"
    elif any(
        getattr(event, name) is not None
        for name in (
            "timestamp",
            "level",
            "method",
            "endpoint",
            "status_code",
            "latency_ms",
            "service",
            "trace_id",
        )
    ):
        event.parse_status = "partial"
    return event


def parse_json_line(line: str, number: int, mask_ipv4: bool) -> LogEvent | None:
    if not line.lstrip().startswith(("{", "[")):
        return None
    try:
        data = redact_json(json.loads(line), mask_ipv4=mask_ipv4)
    except (ValueError, RecursionError):
        return LogEvent(line_number=number, message=redact_text(line, mask_ipv4=mask_ipv4))
    if not isinstance(data, dict):
        return LogEvent(line_number=number, message=json.dumps(data, ensure_ascii=False))
    method = string(first(data, "method", "http_method"))
    if method is not None:
        method = (
            method.upper()
            if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
            else None
        )
    event = LogEvent(
        line_number=number,
        timestamp=parse_timestamp(first(data, "timestamp", "time")),
        level=normalize_level(first(data, "level", "severity")),
        service=string(first(data, "service", "service_name")),
        method=method,
        endpoint=string(first(data, "endpoint", "path")),
        status_code=status_code(first(data, "status_code", "status")),
        latency_ms=latency(first(data, "latency_ms", "duration_ms")),
        trace_id=MASK
        if any(key in data for key in ("trace_id", "traceId", "correlation_id"))
        else None,
        message=string(first(data, "message", "msg")) or json.dumps(data, ensure_ascii=False),
    )
    return classify(event)


def parse_plain_line(line: str, number: int, mask_ipv4: bool) -> LogEvent:
    safe = redact_text(line, mask_ipv4=mask_ipv4)
    timestamp = TIMESTAMP.search(safe)
    level = LEVEL.search(safe)
    request = REQUEST.search(safe)
    status = STATUS.search(safe)
    if status is None and request is not None:
        status = re.match(r"\s+(\d{3})\b", safe[request.end() :])
    duration = LATENCY.search(safe)
    service = SERVICE.search(safe)
    milliseconds = latency(duration.group(1)) if duration else None
    if milliseconds is not None and duration.group(2).lower() in {"s", "seconds"}:
        milliseconds *= 1000
        milliseconds = latency(milliseconds)
    return classify(
        LogEvent(
            line_number=number,
            timestamp=parse_timestamp(timestamp.group()) if timestamp else None,
            level=normalize_level(level.group()) if level else None,
            service=service.group(1) if service else None,
            method=request.group(1).upper() if request else None,
            endpoint=request.group(2) if request else None,
            status_code=status_code(status.group(1)) if status else None,
            latency_ms=milliseconds,
            trace_id=MASK if TRACE.search(safe) else None,
            message=safe,
        )
    )


LineParser = Callable[[str, int, bool], LogEvent | None]
PARSERS: tuple[LineParser, ...] = (parse_json_line, parse_plain_line)


def parse_lines(
    lines: Iterable[str], *, mask_ipv4: bool = False, parsers: tuple[LineParser, ...] = PARSERS
) -> ParseResult:
    """Parse in registry order; no raw line is retained in the returned result."""
    result = ParseResult()
    for number, raw in enumerate(lines, start=1):
        result.total_lines += 1
        line = raw.rstrip("\r\n")
        if not line.strip():
            result.blank += 1
            continue
        event = None
        for parser in parsers:
            event = parser(line, number, mask_ipv4)
            if event is not None:
                break
        if event is None:
            event = LogEvent(line_number=number, message=redact_text(line, mask_ipv4=mask_ipv4))
        result.events.append(event)
        setattr(result, event.parse_status, getattr(result, event.parse_status) + 1)
    return result
