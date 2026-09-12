"""Exercise PostgreSQL migrations in temporary schemas rolled back on completion."""

import argparse
from datetime import datetime, timezone
from uuid import uuid4

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select, text

from app import models  # noqa: F401 -- Register all tables for comparison.
from app.config import Settings
from app.container import container_settings
from app.database import Base, create_database_engine
from app.migration_state import verify_schema
from scripts.migrate import BASELINE, migration_config, upgrade_database


def verify(engine) -> None:
    for legacy in (False, True):
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                # Generated identifier contains only a fixed prefix and UUID hex.
                schema = "migration_test_" + uuid4().hex
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                table = None
                if legacy:
                    module = (
                        ScriptDirectory.from_config(migration_config())
                        .get_revision(BASELINE)
                        .module
                    )
                    metadata = module.baseline_metadata()
                    metadata.create_all(connection)
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
                upgrade_database(connection)
                verify_schema(connection)
                if compare_metadata(
                    MigrationContext.configure(connection, opts={"compare_server_default": True}),
                    Base.metadata,
                ):
                    raise RuntimeError("Migration/model mismatch")
                if table is not None:
                    if dict(connection.execute(select(table)).mappings().one()) != before:
                        raise RuntimeError("Legacy data changed")
                # Only this disposable schema is downgraded. Application tables are untouched.
                command.downgrade(migration_config(connection), BASELINE)
                upgrade_database(connection)
                verify_schema(connection)
            finally:
                transaction.rollback()


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
            "PASS: fresh and legacy PostgreSQL migrations, schema comparison, preserved data, downgrade/re-upgrade; temporary schemas rolled back."
        )
    except Exception:
        print(
            "Migration verification failed; check database access and migrations. No connection details are displayed."
        )
        raise SystemExit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
