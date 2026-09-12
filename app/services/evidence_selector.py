"""Select bounded, diverse redacted evidence in deterministic source order."""

from pydantic import BaseModel

from app.services.error_signatures import error_signature, is_error
from app.services.log_parser import LogEvent


class Evidence(BaseModel):
    evidence_id: str
    event: LogEvent
    reasons: list[str]


def select_evidence(events: list[LogEvent], *, max_items: int = 30) -> list[Evidence]:
    """Prefer one representative per signature, then context and up to three repeats."""
    if not 1 <= max_items <= 100:
        raise ValueError("Evidence limit must be between 1 and 100.")
    ordered = sorted(events, key=lambda event: event.line_number)
    if len({event.line_number for event in ordered}) != len(ordered):
        raise ValueError("Evidence selection expects unique line numbers from one source file.")
    groups: dict[str, list[LogEvent]] = {}
    errors = [event for event in ordered if is_error(event)]
    for event in ordered:
        if is_error(event) or event.level in {"WARN", "WARNING"} or (event.latency_ms or 0) >= 1000:
            groups.setdefault(error_signature(event), []).append(event)
    selected: dict[int, tuple[LogEvent, list[str]]] = {}

    def add(event: LogEvent, reason: str) -> None:
        if event.line_number in selected:
            reasons = selected[event.line_number][1]
            if reason not in reasons:
                reasons.append(reason)
        elif len(selected) < max_items:
            selected[event.line_number] = (event, [reason])

    def severity(group: list[LogEvent]) -> tuple[int, int]:
        rank = min(
            0 if event.level in {"CRITICAL", "FATAL"} else 1 if is_error(event) else 2
            for event in group
        )
        return rank, group[0].line_number

    ranked_groups = sorted(groups.values(), key=severity)
    for group in ranked_groups:
        add(group[0], "distinct_signature")
    if errors:
        add(errors[0], "first_error")
        add(errors[-1], "last_error")
    if groups:
        slowest = max(
            (event for group in groups.values() for event in group),
            key=lambda event: (event.latency_ms or 0, -event.line_number),
        )
        if slowest.latency_ms is not None:
            add(slowest, "highest_latency")
    if errors:
        first_index = ordered.index(errors[0])
        for index in (first_index - 1, first_index + 1):
            if 0 <= index < len(ordered):
                add(ordered[index], "initial_failure_context")
        for event in ordered:
            if (
                event.line_number > errors[-1].line_number
                and not is_error(event)
                and event.status_code is not None
                and 200 <= event.status_code < 400
            ):
                add(event, "successful_request_after_last_error_not_confirmed_recovery")
                break
    for group in ranked_groups:
        add(group[-1], "last_occurrence")
        if len(group) > 2:
            add(
                max(group, key=lambda event: (event.latency_ms or 0, -event.line_number)),
                "signature_highest_latency",
            )
    return [
        Evidence(evidence_id=f"E{index}", event=event.model_copy(deep=True), reasons=reasons)
        for index, (event, reasons) in enumerate(
            (selected[key] for key in sorted(selected)), start=1
        )
    ]
