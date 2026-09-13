"""Worker-invoked analysis with its own session and safe failure reporting."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.analysis_schemas import IncidentAnalysis, validate_evidence_references
from app.config import Settings
from app.models import Incident, IncidentStatus
from app.models import IncidentAnalysis as IncidentAnalysisRow
from app.services.error_signatures import with_error_signatures
from app.services.evidence_selector import Evidence, select_evidence
from app.services.file_parser import parse_incident_files
from app.services.llm_service import generate_analysis
from app.services.redactor import redact_json
from app.services.statistics import calculate_statistics


def run_analysis(incident_id: str, factory: sessionmaker[Session], settings: Settings) -> None:
    """Compatibility entry point; all execution now uses persistent jobs."""
    from app.services.jobs import active_job, new_job, run_job

    with factory() as session:
        incident = session.scalar(
            select(Incident).where(Incident.id == incident_id).with_for_update()
        )
        if incident is None or incident.status != IncidentStatus.UPLOADED:
            return
        job = active_job(session, incident_id)
        if job is None:
            job = new_job(session, incident)
            session.commit()
        job_id = job.id
    run_job(job_id, factory, settings)


def perform_analysis(session, incident, settings, stage, *, resume=False):
    """Shared stages; durable jobs reuse committed redacted statistics on recovery."""
    if resume and incident.statistics is not None:
        statistics = {key: value for key, value in incident.statistics.items() if key != "evidence"}
        evidence = [Evidence.model_validate(item) for item in incident.statistics["evidence"]]
    else:
        parsed = parse_incident_files(session, incident, settings)
        stage(IncidentStatus.CALCULATING)
        events = with_error_signatures(parsed.events)
        statistics = calculate_statistics(parsed)
        evidence = select_evidence(events, max_items=settings.max_evidence_items)
        incident.statistics = {
            **statistics,
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
        stage(IncidentStatus.CALCULATING)
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
    usage = generated.get("usage") or {}
    session.add(
        IncidentAnalysisRow(
            incident_id=incident.id,
            prompt_version=generated.get("prompt_version"),
            provider=generated.get("provider", "unknown"),
            model=generated.get("model"),
            result=analysis.model_dump(mode="json"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
            duration_seconds=generated.get("duration_seconds"),
        )
    )
    incident.severity = analysis.severity
    incident.error_message = None
    incident.completed_at = datetime.now(timezone.utc)
    stage(IncidentStatus.COMPLETED)
    try:
        from app.services.similar_incidents import index_incident

        index_incident(session, incident, settings)
    except Exception:
        session.rollback()  # Analysis is already committed; embedding can be retried later.
