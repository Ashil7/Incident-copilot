"""Explicit, checked database migration command; never display connection secrets."""

import argparse

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, inspect, text

from app.config import PROJECT_ROOT, Settings
from app.container import container_settings
from app.database import create_database_engine

BASELINE = "0001_phase1"


def migration_config(connection: Connection | None = None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def inspect_state(connection: Connection) -> str:
    """Refuse to baseline an unknown schema; return only a safe status label."""
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    heads = context.get_current_heads()
    scripts = ScriptDirectory.from_config(migration_config())
    if heads:
        if len(heads) != 1 or heads[0] not in {item.revision for item in scripts.walk_revisions()}:
            raise RuntimeError("Unsupported database revision. Review migration history.")
        return heads[0]
    inspector = inspect(connection)
    tables = set(inspector.get_table_names()) - {"alembic_version"}
    if not tables:
        return "empty"
    if tables != {"incidents"}:
        raise RuntimeError("Unversioned database has unexpected tables; migration stopped.")
    metadata = scripts.get_revision(BASELINE).module.baseline_metadata()
    if compare_metadata(context, metadata):
        raise RuntimeError("Existing schema differs from Phase 1; migration stopped.")
    # Alembic autogenerate does not reliably detect changed enum labels.
    if connection.dialect.name == "postgresql":
        enums = {item["name"]: item["labels"] for item in inspector.get_enums()}
        for name in ("environment", "status"):
            expected = metadata.tables["incidents"].c[name].type
            if enums.get(expected.name) != expected.enums:
                raise RuntimeError("Existing enum differs from Phase 1; migration stopped.")
    return "legacy"


def upgrade_database(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        # Serialize cooperating migration processes for this database transaction.
        connection.execute(text("SELECT pg_advisory_xact_lock(2101001)"))
    state = inspect_state(connection)
    config = migration_config(connection)
    if state == "legacy":
        command.stamp(config, BASELINE)
    command.upgrade(config, "head")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "upgrade"])
    parser.add_argument("--container", action="store_true", help="Connect to Compose db:5432")
    args = parser.parse_args()
    engine = None
    try:
        settings = Settings()
        if args.container:
            settings = container_settings(settings)
        engine = create_database_engine(settings)
        with engine.begin() as connection:
            if args.action == "upgrade":
                upgrade_database(connection)
            state = inspect_state(connection)
        print("Database migration state:", state)
    except Exception:
        print(
            "Migration check/action failed. Check connectivity and schema compatibility; no credentials are displayed."
        )
        raise SystemExit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
