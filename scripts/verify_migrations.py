"""Exercise PostgreSQL migrations in temporary schemas rolled back on completion."""

import argparse
from datetime import datetime, timezone
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app import models  # noqa: F401 -- Register all tables for comparison.
from app.config import Settings
from app.container import container_settings
from app.database import Base, create_database_engine
from app.migration_state import verify_schema
from app.services.jobs import incident_lock
from scripts.migrate import BASELINE, inspect_state, migration_config


class MigrationVerificationFailure(RuntimeError):
    def __init__(self, stage: str, error: Exception):
        super().__init__(stage)
        self.stage = stage
        self.error_type = type(error).__name__
        self.safe_reason = str(error) if isinstance(error, RuntimeError) else ""


def summarize_differences(differences) -> str:
    """Return only operation/table/column identifiers from Alembic differences."""
    summaries = []
    for difference in differences:
        items = difference if isinstance(difference, list) else [difference]
        for item in items:
            if not isinstance(item, tuple) or not item:
                summaries.append("unknown")
                continue
            operation = str(item[0])
            names = []
            if len(item) > 1 and hasattr(item[1], "name"):
                names.append(str(item[1].name))
            elif len(item) > 3:
                names.extend(str(value) for value in item[2:4] if isinstance(value, str))
            summaries.append(":".join([operation, *names]))
    return ",".join(sorted(set(summaries)))[:300]


def upgrade_disposable(connection, schema: str) -> None:
    """Upgrade a known temporary schema while keeping public extension types visible."""
    connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
    state = inspect_state(connection)
    connection.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
    config = migration_config(connection)
    if state == "legacy":
        command.stamp(config, BASELINE)
    command.upgrade(config, "head")


def verify(engine) -> None:
    stage = "worker lock exclusion"
    try:
        # Separate physical connections must exclude each other; no application rows touched.
        lock_id = str(uuid4())
        with incident_lock(engine, lock_id) as first:
            with incident_lock(engine, lock_id) as second:
                if not first or second:
                    raise RuntimeError("Worker lock exclusion failed")
        with incident_lock(engine, lock_id) as released:
            if not released:
                raise RuntimeError("Worker lock was not released")
        for legacy in (False, True):
            scenario = "legacy" if legacy else "fresh"
            stage = f"{scenario} schema setup"
            with engine.connect() as connection:
                transaction = connection.begin()
                try:
                    # Generated identifier contains only a fixed prefix and UUID hex.
                    schema = "migration_test_" + uuid4().hex
                    connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                    connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                    # Shadow the live public revision table so Alembic tracks only this
                    # disposable schema while exercising fresh and legacy upgrades.
                    connection.execute(
                        text(
                            "CREATE TABLE alembic_version "
                            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
                        )
                    )
                    table = None
                    if legacy:
                        module = (
                            ScriptDirectory.from_config(migration_config())
                            .get_revision(BASELINE)
                            .module
                        )
                        metadata = module.baseline_metadata()
                        # A same-named current table is visible in public. This frozen
                        # baseline must still be created in the first search-path schema.
                        metadata.create_all(connection, checkfirst=False)
                        table = metadata.tables["incidents"]
                        connection.execute(
                            table.insert().values(
                                id=str(uuid4()),
                                title="Synthetic migration test",
                                environment="DEV",
                                status="COMPLETED",
                                statistics={"error_count": 0},
                                analysis={"provider": "deterministic"},
                                created_at=datetime.now(timezone.utc),
                            )
                        )
                        before = dict(connection.execute(select(table)).mappings().one())
                    stage = f"{scenario} migration execution"
                    upgrade_disposable(connection, schema)
                    stage = f"{scenario} revision verification"
                    verify_schema(connection)
                    stage = f"{scenario} model comparison"
                    differences = compare_metadata(
                        MigrationContext.configure(
                            connection, opts={"compare_server_default": True}
                        ),
                        Base.metadata,
                    )
                    if differences:
                        stage += f" [{summarize_differences(differences)}]"
                        raise RuntimeError("Migration/model mismatch")
                    if table is not None and (
                        dict(connection.execute(select(table)).mappings().one()) != before
                    ):
                        raise RuntimeError("Legacy data changed")
                    stage = f"{scenario} active-job uniqueness"
                    incident_id = connection.execute(
                        models.Incident.__table__.insert()
                        .values(title="Synthetic job uniqueness check")
                        .returning(models.Incident.id)
                    ).scalar_one()
                    jobs = models.AnalysisJob.__table__
                    connection.execute(
                        jobs.insert().values(incident_id=incident_id, status="PENDING")
                    )
                    try:
                        with connection.begin_nested():
                            connection.execute(
                                jobs.insert().values(incident_id=incident_id, status="RUNNING")
                            )
                    except IntegrityError:
                        pass
                    else:
                        raise RuntimeError("Active-job uniqueness failed")
                    connection.execute(
                        jobs.update()
                        .where(jobs.c.incident_id == incident_id)
                        .values(status="COMPLETED")
                    )
                    connection.execute(
                        jobs.insert().values(incident_id=incident_id, status="PENDING")
                    )
                    stage = f"{scenario} downgrade"
                    # Only this disposable schema is downgraded. Application tables are untouched.
                    command.downgrade(migration_config(connection), BASELINE)
                    stage = f"{scenario} re-upgrade"
                    upgrade_disposable(connection, schema)
                    verify_schema(connection)
                finally:
                    transaction.rollback()
    except MigrationVerificationFailure:
        raise
    except Exception as error:
        raise MigrationVerificationFailure(stage, error) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args()
    engine = None
    try:
        settings = Settings()
        if args.container:
            settings = container_settings(settings)
        engine = create_database_engine(settings)
        verify(engine)
        print(
            "PASS: fresh and legacy PostgreSQL migrations, schema comparison, preserved data, downgrade/re-upgrade, worker lock exclusion, active-job uniqueness; temporary schemas rolled back."
        )
    except MigrationVerificationFailure as error:
        reason = f": {error.safe_reason}" if error.safe_reason else ""
        print(
            f"Migration verification failed during {error.stage} "
            f"({error.error_type}){reason}; no connection details are displayed."
        )
        raise SystemExit(1) from None
    except Exception as error:
        print(
            "Migration verification failed during setup "
            f"({type(error).__name__}); no connection details are displayed."
        )
        raise SystemExit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
