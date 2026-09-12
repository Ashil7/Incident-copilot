"""In-process background analysis with its own session and safe failure reporting."""

import logging
from datetime import datetime, timezone
from time import monotonic

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from app.analysis_schemas import IncidentAnalysis, validate_evidence_references
from app.config import Settings
from app.models import Incident, IncidentStatus
from app.observability import log_event
from app.services.error_signatures import with_error_signatures
from app.services.evidence_selector import select_evidence
from app.services.file_parser import parse_incident_files
from app.services.llm_service import generate_analysis
from app.services.redactor import redact_json
from app.services.statistics import calculate_statistics


def run_analysis(incident_id: str, factory: sessionmaker[Session], settings: Settings) -> None:
    """Claim one uploaded incident; never accept a request session or raw file bytes."""
    claimed = False
    started = monotonic()
    try:
        with factory() as session:
            claim = session.execute(
                update(Incident)
                .where(Incident.id == incident_id, Incident.status == IncidentStatus.UPLOADED)
                .values(status=IncidentStatus.PARSING)
            )
            claimed = claim.rowcount == 1
            session.commit()
            if not claimed:
                return
            incident = session.get(Incident, incident_id)

            def stage(status: IncidentStatus) -> None:
                incident.status = status
                session.commit()

            parsed = parse_incident_files(session, incident, settings)
            stage(IncidentStatus.CALCULATING)
            events = with_error_signatures(parsed.events)
            statistics = calculate_statistics(parsed)
            evidence = select_evidence(events, max_items=settings.max_evidence_items)
            incident.statistics = {
                **statistics,
                "evidence": [item.model_dump(mode="json") for item in evidence],
            }
            session.commit()
            if evidence:
                stage(IncidentStatus.GENERATING_ANALYSIS)
                generated = generate_analysis(
                    {
                        "statistics": statistics,
                        "evidence": [item.model_dump(mode="json") for item in evidence],
                    },
                    settings,
                )
            else:
                generated = {
                    "provider": "deterministic",
                    "model": None,
                    "prompt_version": None,
                    "duration_seconds": 0,
                    "usage": None,
                    "result": {
                        "title": "No evidence candidates selected",
                        "severity": "LOW",
                        "incident_type": "INSUFFICIENT_EVIDENCE",
                        "summary": "No events met the configured evidence-selection criteria. This does not establish service health.",
                        "affected_components": [],
                        "observations": [],
                        "possible_causes": [],
                        "recommended_checks": [],
                        "information_gaps": ["Unparsed or missing records may hide failures."],
                        "suggested_escalation_team": None,
                    },
                }
            stage(IncidentStatus.VALIDATING)
            analysis = IncidentAnalysis.model_validate(generated["result"])
            ids = {item.evidence_id for item in evidence}
            validate_evidence_references(analysis, ids)
            # Provider output is untrusted too: mask known patterns before persistence.
            analysis = IncidentAnalysis.model_validate(
                redact_json(analysis.model_dump(mode="json"), mask_ipv4=True)
            )
            validate_evidence_references(analysis, ids)
            incident.analysis = {**generated, "result": analysis.model_dump(mode="json")}
            incident.severity = analysis.severity
            incident.error_message = None
            incident.completed_at = datetime.now(timezone.utc)
            stage(IncidentStatus.COMPLETED)
            log_event(
                "analysis.completed",
                incident_id=incident_id,
                duration_ms=round((monotonic() - started) * 1000, 3),
            )
    except Exception:
        # Exiting the session context rolls back pending work. Use a fresh session
        # because the original may have failed during a transaction or commit.
        if claimed:
            try:
                with factory() as failure_session:
                    incident = failure_session.get(Incident, incident_id)
                    if incident is not None and incident.status != IncidentStatus.COMPLETED:
                        incident.status = IncidentStatus.FAILED
                        incident.analysis = None
                        incident.error_message = "Analysis failed. Check model configuration, provider availability, and uploaded data."
                        incident.completed_at = datetime.now(timezone.utc)
                        failure_session.commit()
            except Exception:
                log_event(
                    "analysis.failure_persist_failed", level=logging.ERROR, incident_id=incident_id
                )
            log_event(
                "analysis.failed",
                level=logging.ERROR,
                incident_id=incident_id,
                error_code="ANALYSIS_FAILED",
                duration_ms=round((monotonic() - started) * 1000, 3),
            )
        else:
            log_event("analysis.claim_failed", level=logging.ERROR, incident_id=incident_id)
