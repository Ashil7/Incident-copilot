"""Diversity, ordering, context, and limits for evidence selection."""

import pytest

from app.services.evidence_selector import select_evidence
from app.services.log_parser import LogEvent, parse_lines


def test_empty_and_healthy_logs() -> None:
    assert select_evidence([]) == []
    assert select_evidence(parse_lines(["INFO GET /healthy 200 10ms"]).events) == []


def test_cap_stable_ids_and_order() -> None:
    events = [
        LogEvent(line_number=i, level="ERROR", message=f"unique error {'x' * i}")
        for i in range(1, 101)
    ]
    selected = select_evidence(events)
    assert len(selected) == 30
    assert [item.evidence_id for item in selected] == [f"E{i}" for i in range(1, 31)]
    assert select_evidence(list(reversed(events))) == selected
    assert len(select_evidence(events, max_items=5)) == 5


def test_repeated_errors_do_not_fill_budget() -> None:
    events = [
        LogEvent(line_number=i, level="ERROR", message="same failure", latency_ms=i)
        for i in range(1, 101)
    ]
    selected = select_evidence(events)
    assert len(selected) <= 4  # First/last/slowest plus immediate context.
    assert {1, 100} <= {item.event.line_number for item in selected}


def test_context_slowest_and_possible_recovery() -> None:
    events = parse_lines(
        [
            "INFO GET /a 200 10ms",
            "ERROR GET /a 500 100ms",
            "WARN slow 2000ms",
            "ERROR GET /a 500 500ms",
            "INFO GET /a 200 10ms",
        ]
    ).events
    selected = select_evidence(events)
    reasons = {reason for item in selected for reason in item.reasons}
    assert "highest_latency" in reasons
    assert "initial_failure_context" in reasons
    assert "successful_request_after_last_error_not_confirmed_recovery" in reasons
    assert {1, 5} <= {item.event.line_number for item in selected}


def test_critical_prioritized_when_budget_is_small() -> None:
    events = parse_lines(["WARNING first", "CRITICAL urgent"]).events
    assert select_evidence(events, max_items=1)[0].event.level == "CRITICAL"


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_invalid_limit(limit: int) -> None:
    with pytest.raises(ValueError):
        select_evidence([], max_items=limit)


def test_duplicate_line_numbers_rejected() -> None:
    event = LogEvent(line_number=1, message="ERROR test", level="ERROR")
    with pytest.raises(ValueError):
        select_evidence([event, event])


def test_selected_evidence_remains_redacted() -> None:
    parsed = parse_lines(["ERROR GET /a?token=synthetic-secret 500 2000ms"])
    safe = select_evidence(parsed.events)[0].model_dump_json()
    assert "synthetic-secret" not in safe
