"""Build redacted incident representations and perform exact cosine comparison."""

from sqlalchemy import select

from app.models import Incident, IncidentEmbedding
from app.services.llm_service import get_provider
from app.services.redactor import redact_text
from app.services.runbooks import cosine


def searchable_text(incident):
    result = (incident.analysis or {}).get("result", {})
    signatures = [
        item.get("value", "")
        for item in (incident.statistics or {}).get("top_error_signatures", [])
    ]
    values = [
        incident.service_name,
        result.get("incident_type"),
        result.get("summary"),
        incident.confirmed_root_cause,
        incident.resolution_notes,
        *signatures,
    ]
    return redact_text("\n".join(value for value in values if value), mask_ipv4=True)[:20000]


def index_incident(session, incident, settings, provider=None):
    text = searchable_text(incident)
    if not text:
        return False
    provider = provider or get_provider(settings)
    result = provider.create_embeddings([text])
    vector = result.vectors[0]
    if len(vector) != settings.embedding_dimensions:
        raise ValueError("Embedding dimensions do not match the schema.")
    session.merge(
        IncidentEmbedding(
            incident_id=incident.id,
            searchable_summary=text,
            embedding=vector,
        )
    )
    session.commit()
    return True


def similar_incidents(session, incident, settings):
    current = session.get(IncidentEmbedding, incident.id)
    if current is None:
        return []
    query = (
        select(IncidentEmbedding, Incident)
        .join(Incident, Incident.id == IncidentEmbedding.incident_id)
        .where(
            IncidentEmbedding.incident_id != incident.id,
            Incident.owner_user_id == incident.owner_user_id,
        )
    )
    if session.bind.dialect.name == "postgresql":
        distance = IncidentEmbedding.embedding.cosine_distance(list(current.embedding))
        rows = session.execute(
            query.add_columns(distance.label("distance"))
            .where(distance <= 1 - settings.retrieval_similarity_threshold)
            .order_by(Incident.resolution_notes.is_(None), distance, Incident.id)
            .limit(5)
        )
        return [(1 - float(distance_value), other) for _, other, distance_value in rows]
    rows = session.execute(query).all()
    ranked = sorted(
        (
            (cosine(list(current.embedding), list(vector.embedding)), other)
            for vector, other in rows
        ),
        key=lambda item: (item[1].resolution_notes is None, -item[0], item[1].id),
    )
    return [item for item in ranked[:5] if item[0] >= settings.retrieval_similarity_threshold]


def similarity_label(score):
    if score >= 0.8:
        return "very similar"
    if score >= 0.6:
        return "similar"
    return "possibly related"
