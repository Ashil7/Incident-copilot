"""Request correlation and allowlisted JSON logs without request payloads."""

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import UUID

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)
EVENTS = {
    "request.completed",
    "request.failed",
    "background.failed",
    "analysis.completed",
    "analysis.failed",
    "analysis.claim_failed",
    "analysis.failure_persist_failed",
    "storage.cleanup_deferred",
    "storage.uncommitted_cleanup_failed",
}


class JsonFormatter(logging.Formatter):
    def format(self, record):
        data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.msg
            if isinstance(record.msg, str) and record.msg in EVENTS
            else "application.event",
            "request_id": request_id_context.get(),
        }
        fields = getattr(record, "safe_fields", {})
        for key in ("user_id", "incident_id", "job_id"):
            value = fields.get(key)
            if value is not None:
                try:
                    data[key] = str(UUID(str(value)))
                except ValueError:
                    pass
        for key in ("status_code", "duration_ms"):
            if isinstance(fields.get(key), (int, float)):
                data[key] = fields[key]
        for key in ("route", "method", "error_code"):
            if key in fields:
                data[key] = fields[key]  # Only server-selected values supplied by middleware.
        error_type = fields.get("error_type")
        if isinstance(error_type, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", error_type):
            data["error_type"] = error_type
        # Never format record.args, exception text, tracebacks, or arbitrary extras.
        return json.dumps(data)


def configure_logging():
    logger = logging.getLogger("app")
    if not any(handler.get_name() == "incident_json" for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.set_name("incident_json")
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Raw Uvicorn access lines include paths and query strings; our events use route templates.
    logging.getLogger("uvicorn.access").disabled = True


def log_event(event: str, *, level=logging.INFO, **fields):
    logging.getLogger("app.events").log(level, event, extra={"safe_fields": fields})
