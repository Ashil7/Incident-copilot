"""Deterministic statistics over redacted events; no external services."""

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.services.error_signatures import error_signature, is_error
from app.services.log_parser import LogEvent, ParseResult
from app.services.redactor import MASK


def percentile(values: list[float], percent: float) -> float | None:
    """Linear interpolation at index (n - 1) * percent / 100 in sorted values."""
    if not math.isfinite(percent) or not 0 <= percent <= 100:
        raise ValueError("Percent must be between 0 and 100.")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Percentile values must be finite.")
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower, upper = math.floor(position), math.ceil(position)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def utc_timestamp(event: LogEvent) -> datetime | None:
    value = event.timestamp
    if value is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def top_counts(values: list[str], limit: int = 5) -> list[dict[str, Any]]:
    return [
        {"value": value, "count": count}
        for value, count in sorted(Counter(values).items(), key=lambda item: (-item[1], item[0]))[
            :limit
        ]
    ]


def calculate_statistics(parsed: ParseResult) -> dict[str, Any]:
    """Known HTTP status events are request observations, not guaranteed unique requests."""
    events = parsed.events
    errors = [event for event in events if is_error(event)]
    requests = [event for event in events if event.status_code is not None]
    http_errors = [event for event in requests if event.status_code >= 400]
    durations = [
        event.latency_ms
        for event in events
        if event.latency_ms is not None
        and math.isfinite(event.latency_ms)
        and event.latency_ms >= 0
    ]
    timed_errors = [
        (utc_timestamp(event), event) for event in errors if utc_timestamp(event) is not None
    ]
    timed_errors.sort(key=lambda item: (item[0], item[1].line_number))
    buckets = Counter(time.replace(second=0, microsecond=0).isoformat() for time, _ in timed_errors)
    timeline = []
    if timed_errors:
        for label, (time, event) in (
            ("first_error", timed_errors[0]),
            ("last_error", timed_errors[-1]),
        ):
            timeline.append(
                {"kind": label, "timestamp": time.isoformat(), "line_number": event.line_number}
            )
        peak = min(buckets, key=lambda key: (-buckets[key], key))
        timeline.append({"kind": "peak_error_minute", "timestamp": peak, "count": buckets[peak]})
    return {
        "total_lines": parsed.total_lines,
        "total_events": len(events),
        "parsed_events": parsed.parsed,
        "partial_events": parsed.partial,
        "unparsed_events": parsed.unparsed,
        "blank_lines": parsed.blank,
        "error_count": len(errors),
        "warning_count": sum(event.level in {"WARN", "WARNING"} for event in events),
        "level_counts": dict(sorted(Counter(event.level or "UNKNOWN" for event in events).items())),
        "status_counts": dict(
            sorted(Counter(str(event.status_code) for event in requests).items())
        ),
        "request_observation_count": len(requests),
        "http_error_count": len(http_errors),
        "http_error_rate": len(http_errors) / len(requests) if requests else None,
        "top_affected_endpoints": top_counts(
            [event.endpoint for event in errors if event.endpoint]
        ),
        "top_affected_services": top_counts([event.service for event in errors if event.service]),
        "top_error_signatures": top_counts([error_signature(event) for event in errors]),
        "latency_ms": {
            "count": len(durations),
            "min": min(durations) if durations else None,
            "max": max(durations) if durations else None,
            "average": sum(value / len(durations) for value in durations) if durations else None,
            **{f"p{p}": percentile(durations, p) for p in (50, 90, 95, 99)},
        },
        "first_error_timestamp": timed_errors[0][0].isoformat() if timed_errors else None,
        "last_error_timestamp": timed_errors[-1][0].isoformat() if timed_errors else None,
        "errors_without_comparable_timestamp": len(errors) - len(timed_errors),
        "error_minute_buckets": dict(sorted(buckets.items())),
        "timeline": timeline,
        "error_trace_ids": sorted(
            {event.trace_id for event in errors if event.trace_id and event.trace_id != MASK}
        ),
        "redacted_error_trace_count": sum(event.trace_id == MASK for event in errors),
    }
