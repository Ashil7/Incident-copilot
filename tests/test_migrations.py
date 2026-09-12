"""Test real revision operations on disposable databases, never the user's .env."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.database import Base
from app.migration_state import SCHEMA_HEAD, verify_schema
from app.models import Incident, User
from scripts.migrate import BASELINE, inspect_state, migration_config, upgrade_database


def baseline_metadata():
    return (
        ScriptDirectory.from_config(migration_config())
        .get_revision(BASELINE)
        .module.baseline_metadata()
    )


def test_fresh_upgrade_matches_models_and_repeated_upgrade_is_safe(database_engine):
    with database_engine.begin() as connection:
        upgrade_database(connection)
        verify_schema(connection)
        assert inspect_state(connection) == SCHEMA_HEAD
        assert set(inspect(connection).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        assert (
            compare_metadata(
                MigrationContext.configure(connection, opts={"compare_server_default": True}),
                Base.metadata,
            )
            == []
        )


def test_adopt_legacy_preserves_every_original_column():
    engine = create_engine("sqlite://")
    metadata = baseline_metadata()
    table = metadata.tables["incidents"]
    row = {
        "id": str(uuid4()),
        "title": "Preserve synthetic incident",
        "service_name": "demo",
        "environment": "DEV",
        "status": "COMPLETED",
        "original_filename": "synthetic.log",
        "stored_file_path": "/legacy/synthetic.log",
        "statistics": {"error_count": 1},
        "analysis": {"provider": "deterministic", "result": {"summary": "Synthetic"}},
        "error_message": None,
        "created_at": datetime(2026, 9, 12, tzinfo=timezone.utc),
        "completed_at": datetime(2026, 9, 12, 1, tzinfo=timezone.utc),
    }
    try:
        with engine.begin() as connection:
            metadata.create_all(connection)
            connection.execute(table.insert().values(**row))
            before = dict(connection.execute(select(table)).mappings().one())
            assert inspect_state(connection) == "legacy"
            upgrade_database(connection)
            assert dict(connection.execute(select(table)).mappings().one()) == before
            assert connection.execute(text("SELECT owner_user_id FROM incidents")).scalar() is None
            assert connection.execute(
                text("SELECT updated_at = created_at FROM incidents")
            ).scalar()
    finally:
        engine.dispose()


def test_unknown_legacy_schema_is_not_stamped():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            baseline_metadata().create_all(connection)
            connection.execute(text("ALTER TABLE incidents ADD COLUMN unexpected TEXT"))
            with pytest.raises(RuntimeError, match="differs from Phase 1"):
                upgrade_database(connection)
            assert not inspect(connection).has_table("alembic_version")
    finally:
        engine.dispose()


def test_downgrade_and_reupgrade_on_disposable_database(database_engine):
    with database_engine.begin() as connection:
        command.downgrade(migration_config(connection), BASELINE)
        assert set(inspect(connection).get_table_names()) == {"incidents", "alembic_version"}
        upgrade_database(connection)
        verify_schema(connection)


def test_unmigrated_startup_fails_without_creating_tables(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    from app.main import create_app

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    # Keep the in-memory database alive to inspect what startup did.
    monkeypatch.setattr(engine, "dispose", lambda: None)
    with pytest.raises(RuntimeError, match="schema is not current"):
        with TestClient(create_app(Settings(_env_file=None), database_engine=engine)):
            pass
    assert inspect(engine).get_table_names() == []


def test_normalized_email_unique_and_owner_foreign_key(database_engine):
    with database_engine.connect() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.commit()
        with Session(connection) as session:
            user = User(
                email=" DEMO@EXAMPLE.TEST ", password_hash="synthetic-hash", full_name="Demo"
            )
            session.add(user)
            session.commit()
            assert user.email == "demo@example.test"
            session.add(
                User(email="demo@example.test", password_hash="fake", full_name="Duplicate")
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            session.add(Incident(title="Invalid owner", owner_user_id=str(uuid4())))
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
