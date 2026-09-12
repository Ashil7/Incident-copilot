"""Hand-calculated expectations for deterministic incident statistics."""

from pathlib import Path

import pytest

from app.services.error_signatures import with_error_signatures
from app.services.log_parser import parse_lines
from app.services.statistics import calculate_statistics, percentile


def test_percentile_empty_single_and_interpolation() -> None:
    assert percentile([], 95) is None
    assert percentile([7], 99) == 7
    assert percentile([30, 0, 20, 10], 50) == 15
    assert percentile([0, 10, 20, 30], 95) == pytest.approx(28.5)
    assert percentile([0, 10], 0) == 0
    assert percentile([0, 10], 100) == 10


@pytest.mark.parametrize("value", [-1, 101, float("nan")])
def test_invalid_percentile(value: float) -> None:
    with pytest.raises(ValueError):
        percentile([1], value)


def test_nonfinite_percentile_data() -> None:
    with pytest.raises(ValueError):
        percentile([float("inf")], 50)


def test_fixture_statistics() -> None:
    path = Path(__file__).parent / "fixtures" / "synthetic_logs.txt"
    with path.open(encoding="utf-8") as source:
        stats = calculate_statistics(parse_lines(source, mask_ipv4=True))
    assert stats["total_lines"] == 14
    assert stats["total_events"] == 13
    assert stats["error_count"] == 6
    assert stats["warning_count"] == 1
    assert stats["request_observation_count"] == 8
    assert stats["http_error_rate"] == 5 / 8
    assert stats["latency_ms"]["average"] == pytest.approx(1220.25)
    assert stats["latency_ms"]["p50"] == 612.5
    assert stats["latency_ms"]["max"] == 5000
    assert stats["top_affected_endpoints"][0] == {"value": "/api/upstream", "count": 2}
    assert stats["error_minute_buckets"] == {"2026-09-11T12:00:00+00:00": 6}


def test_empty_statistics_and_unknown_request_total() -> None:
    stats = calculate_statistics(parse_lines([]))
    assert stats["http_error_rate"] is None
    assert stats["latency_ms"]["p95"] is None
    assert stats["timeline"] == []
    stats = calculate_statistics(parse_lines(["ERROR failure"]))
    assert stats["error_count"] == 1
    assert stats["http_error_rate"] is None


def test_mixed_timezones_no_invented_offset() -> None:
    stats = calculate_statistics(
        parse_lines(
            [
                "2026-09-11T12:00:00+02:00 ERROR first",
                "2026-09-11T11:00:00Z ERROR last",
                "2026-09-11 09:00:00 ERROR unknown offset",
            ]
        )
    )
    assert stats["first_error_timestamp"] == "2026-09-11T10:00:00+00:00"
    assert stats["last_error_timestamp"] == "2026-09-11T11:00:00+00:00"
    assert stats["errors_without_comparable_timestamp"] == 1


def test_signatures_group_variable_ids_without_mutating_events() -> None:
    parsed = parse_lines(
        [
            "2026-09-11T12:00:00Z ERROR order 123 failed",
            "2026-09-11T12:00:01Z ERROR order 456 failed",
            "INFO healthy",
        ]
    )
    enriched = with_error_signatures(parsed.events)
    assert enriched[0].error_signature == enriched[1].error_signature
    assert enriched[2].error_signature is None
    assert parsed.events[0].error_signature is None
    assert calculate_statistics(parsed)["top_error_signatures"][0]["count"] == 2


def test_signatures_ignore_duration_but_keep_http_status() -> None:
    parsed = parse_lines(
        [
            "ERROR GET /api 504 25ms Upstream timeout",
            "ERROR GET /api 504 2.5s Upstream timeout",
            "ERROR GET /api 502 25ms Upstream timeout",
        ]
    )
    enriched = with_error_signatures(parsed.events)
    assert enriched[0].error_signature == enriched[1].error_signature
    assert enriched[0].error_signature != enriched[2].error_signature
    assert [event.latency_ms for event in enriched] == [25, 2500, 25]
