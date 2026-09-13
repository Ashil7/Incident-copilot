from io import BytesIO

from pypdf import PdfReader

from app.models import Incident, LogEvent


def test_public_page_shells_and_static_assets(client):
    for path, text in (
        ("/login", "Sign in"),
        ("/register", "Create account"),
        ("/", "Dashboard"),
        ("/incidents/new", "New incident"),
        ("/runbooks", "Runbooks"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert text in response.text
        assert "app.js" in response.text
    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "textContent" in script.text


def test_event_filters_and_pdf_are_owner_protected(client, incident_user):
    with client.app.state.session_factory() as session:
        incident = Incident(
            title="Synthetic <RCA>",
            owner_user_id=incident_user.id,
            service_name="payments",
            confirmed_root_cause="Synthetic connection exhaustion",
            resolution_notes="Raised the synthetic pool limit",
            statistics={
                "total_events": 1,
                "error_count": 1,
                "evidence": [
                    {
                        "evidence_id": "E1",
                        "event": {
                            "source_file_id": "file-1",
                            "source_line_number": 7,
                            "message": "Synthetic failure <escaped>",
                        },
                    }
                ],
            },
            analysis={
                "result": {
                    "summary": "AI synthetic summary",
                    "possible_causes": [{"cause": "Possible pool pressure", "confidence": 0.5}],
                    "recommended_checks": [
                        {"order": 1, "action": "Inspect metrics", "risk": "READ_ONLY"}
                    ],
                    "information_gaps": ["Capacity history unavailable"],
                }
            },
        )
        session.add(incident)
        session.flush()
        session.add_all(
            [
                LogEvent(
                    incident_id=incident.id,
                    log_file_id="file-1",
                    source_line_number=7,
                    level="ERROR",
                    endpoint="/api/payments",
                    status_code=503,
                    latency_ms=1000,
                    redacted_message="Synthetic failure",
                    is_evidence=True,
                ),
                LogEvent(
                    incident_id=incident.id,
                    log_file_id="file-1",
                    source_line_number=8,
                    level="INFO",
                    endpoint="/health",
                    status_code=200,
                    redacted_message="Healthy",
                    is_evidence=False,
                ),
            ]
        )
        session.commit()
        incident_id = incident.id

    events = client.get(
        f"/api/v1/incidents/{incident_id}/events",
        params={
            "level": "ERROR",
            "status_code": 503,
            "endpoint": "payments",
            "evidence_only": True,
        },
    )
    assert events.status_code == 200
    assert len(events.json()) == 1
    assert events.json()[0]["line_number"] == 7
    assert "storage_key" not in events.text

    response = client.get(f"/api/v1/incidents/{incident_id}/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    text = "\n".join(
        page.extract_text() or "" for page in PdfReader(BytesIO(response.content)).pages
    )
    for expected in (
        "Incident RCA Report",
        "Synthetic <RCA>",
        "Human-confirmed root cause",
        "AI-generated analysis",
        "Possible pool pressure",
        "Synthetic failure <escaped>",
    ):
        assert expected in text


def test_browser_controller_does_not_inject_api_text_as_html(client):
    script = client.get("/static/app.js").text
    assert "textContent" in script
    assert "innerHTML=x" not in script
    assert "eval(" not in script
