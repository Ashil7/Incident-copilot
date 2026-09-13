"""Bounded RCA PDF generation with escaped untrusted text."""

from datetime import datetime, timezone
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas


def incident_pdf(incident, similar=()):
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    width, height = A4
    y = height - 50

    def write(value, style="BodyText"):
        nonlocal y
        safe = str(value or "Not provided")[:8000]
        for line in simpleSplit(safe, styles[style].fontName, styles[style].fontSize, width - 100):
            if y < 55:
                canvas.showPage()
                y = height - 50
            canvas.drawString(50, y, line[:180])
            y -= styles[style].leading
        y -= 5

    write("Incident RCA Report", "Title")
    write(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    write(f"Title: {incident.title}")
    write(f"Service: {incident.service_name}")
    write(f"Environment: {incident.environment}")
    write(f"Status: {incident.status}")
    write(f"Created: {incident.created_at}")
    write(f"Completed: {incident.completed_at}")
    write(f"Human-confirmed severity: {incident.severity}")
    write(f"Human-confirmed root cause: {incident.confirmed_root_cause}")
    write(f"Human-confirmed resolution: {incident.resolution_notes}")
    result = (incident.analysis or {}).get("result") or {}
    write("AI-generated analysis", "Heading2")
    write(result.get("summary"))
    write("Possible causes", "Heading2")
    for cause in result.get("possible_causes", [])[:30]:
        write(f"{cause.get('cause')} (confidence {cause.get('confidence')})")
    write("Recommended checks", "Heading2")
    for check in result.get("recommended_checks", [])[:30]:
        write(f"{check.get('order')}. {check.get('action')} [{check.get('risk')}]")
    write("Information gaps", "Heading2")
    for gap in result.get("information_gaps", [])[:30]:
        write(gap)
    write("Calculated statistics", "Heading2")
    stats = incident.statistics or {}
    for key in (
        "total_events",
        "error_count",
        "warning_count",
        "first_error_timestamp",
        "last_error_timestamp",
    ):
        write(f"{key}: {stats.get(key)}")
    write("Evidence", "Heading2")
    for evidence in stats.get("evidence", [])[:50]:
        event = evidence.get("event", {})
        write(
            f"{evidence.get('evidence_id')} file={event.get('source_file_id')} line={event.get('source_line_number') or event.get('line_number')}: {event.get('message')}"
        )
    write("Similar resolved incidents", "Heading2")
    if not similar:
        write("No similar resolved incident met the retrieval threshold.")
    for score, other in list(similar)[:5]:
        write(f"{other.title} ({score:.2f} similarity): {other.resolution_notes}")
    canvas.save()
    buffer.seek(0)
    return buffer.getvalue()
