"""Verify pgvector tables and exact cosine retrieval with rolled-back synthetic rows."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import create_database_engine
from app.migration_state import verify_schema
from app.models import Incident, IncidentEmbedding, Runbook, RunbookChunk, User
from app.services.runbooks import retrieve_chunks
from app.services.similar_incidents import similar_incidents


def main():
    settings = Settings()
    engine = create_database_engine(settings)
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        verify_schema(connection)
        if connection.dialect.name == "postgresql":
            assert connection.scalar(
                text("SELECT extname FROM pg_extension WHERE extname='vector'")
            )
        user = User(
            email=f"retrieval-{uuid4().hex}@example.com",
            full_name="Synthetic retrieval verifier",
            password_hash="unused-synthetic-hash",
        )
        session.add(user)
        session.flush()
        vector = [1.0, 0.0] + [0.0] * 1534
        runbook = Runbook(
            owner_user_id=user.id,
            title="Synthetic database runbook",
            original_filename="synthetic.txt",
            storage_key=f"{uuid4()}.txt",
            storage_scope="synthetic",
            mime_type="text/plain",
            size_bytes=9,
            sha256="0" * 64,
            status="READY",
        )
        current = Incident(title="Synthetic current", owner_user_id=user.id)
        previous = Incident(
            title="Synthetic resolved", owner_user_id=user.id, resolution_notes="Synthetic fix"
        )
        session.add_all([runbook, current, previous])
        session.flush()
        session.add(
            RunbookChunk(
                runbook_id=runbook.id,
                chunk_index=0,
                text="Inspect synthetic database pool metrics.",
                embedding=vector,
            )
        )
        session.add_all(
            [
                IncidentEmbedding(
                    incident_id=current.id, searchable_summary="database pool", embedding=vector
                ),
                IncidentEmbedding(
                    incident_id=previous.id,
                    searchable_summary="database pool failure",
                    embedding=vector,
                ),
            ]
        )
        session.flush()
        assert retrieve_chunks(session, user, vector, settings)[0][1].runbook_id == runbook.id
        assert similar_incidents(session, current, settings)[0][1].id == previous.id
        print(
            "PASS: vector extension, 1536-dimension storage, exact runbook retrieval, "
            "owner-scoped similar incidents; synthetic rows rolled back."
        )
    except Exception:
        print("Retrieval verification failed; no database or provider details displayed.")
        raise SystemExit(1) from None
    finally:
        session.close()
        transaction.rollback()
        connection.close()
        engine.dispose()


if __name__ == "__main__":
    main()
