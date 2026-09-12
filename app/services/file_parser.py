"""Read verified objects and preserve file-local and combined line numbering."""

import hashlib
from io import StringIO
from pathlib import Path

from app.services.incident_files import file_rows
from app.services.log_parser import ParseResult, parse_lines
from app.services.storage import get_storage


def parse_incident_files(session, incident, settings):
    storage = get_storage(settings)
    rows = file_rows(session, incident.id)
    if not rows:
        # Read-only compatibility for pre-2.4 records; never overwrite their metadata.
        path = Path(incident.stored_file_path or "")
        if path.resolve() != storage.path(path.name).resolve():
            raise ValueError("Legacy object is unavailable.")
        with storage.open(path.name) as source:
            data = source.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_upload_size_mb * 1024 * 1024:
            raise ValueError("Stored upload exceeds the limit.")
        return parse_lines(StringIO(data.decode("utf-8")), mask_ipv4=True)
    if len(rows) > settings.max_files_per_incident:
        raise ValueError("Too many stored files.")
    combined = ParseResult()
    for row in rows:
        if row.storage_scope != storage.scope:
            raise ValueError("File belongs to another storage environment.")
        with storage.open(row.storage_key) as source:
            data = source.read(settings.max_upload_size_mb * 1024 * 1024 + 1)
        if len(data) > settings.max_upload_size_mb * 1024 * 1024 or len(data) != row.size_bytes:
            raise ValueError("Stored upload size mismatch.")
        if hashlib.sha256(data).hexdigest() != row.sha256:
            raise ValueError("Stored upload checksum mismatch.")
        parsed = parse_lines(StringIO(data.decode("utf-8")), mask_ipv4=True)
        for event in parsed.events:
            combined.events.append(
                event.model_copy(
                    update={
                        "line_number": event.line_number + combined.total_lines,
                        "source_line_number": event.line_number,
                        "source_file_id": row.id,
                    }
                )
            )
        for field in ("total_lines", "parsed", "partial", "blank", "unparsed"):
            setattr(combined, field, getattr(combined, field) + getattr(parsed, field))
    return combined
