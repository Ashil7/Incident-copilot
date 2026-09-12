"""Run with python -m scripts.verify_database after starting PostgreSQL."""

from uuid import UUID

from sqlalchemy import inspect, text

from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.models import Environment, Incident, IncidentStatus
from app.schemas import IncidentResponse


def main() -> None:
    engine = create_database_engine(Settings())
    try:
        assert inspect(engine).has_table("incidents"), "Start the API first to create tables."
        with create_session_factory(engine)() as session:
            assert session.scalar(text("SELECT 1")) == 1
            incident = Incident(
                title="Synthetic Milestone 1.2 verification",
                stored_file_path="uploads/synthetic-internal-path.log",
                statistics={"error_count": 2},
            )
            session.add(incident)
            session.flush()
            incident_id = incident.id
            session.expunge_all()
            loaded = session.get(Incident, incident_id)
            assert loaded is not None
            assert str(UUID(loaded.id)) == incident_id
            assert loaded.environment == Environment.DEV
            assert loaded.status == IncidentStatus.CREATED
            assert loaded.created_at.utcoffset() is not None
            assert loaded.statistics == {"error_count": 2}
            response = IncidentResponse.model_validate(loaded).model_dump(mode="json")
            assert "stored_file_path" not in response
            assert response["status"] == "CREATED"
            session.rollback()  # Keep verification data out of the database.
        with create_session_factory(engine)() as session:
            assert session.get(Incident, incident_id) is None
        print(
            "PASS: connectivity, table, UUID, defaults, timezone, JSON, response privacy, rollback"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
