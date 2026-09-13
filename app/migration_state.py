"""Read-only schema version guard; startup never creates or alters tables."""

from alembic.migration import MigrationContext
from sqlalchemy import Connection, text

SCHEMA_HEAD = "0005_phase4_retrieval"


def verify_schema(connection: Connection) -> None:
    connection.execute(text("SELECT 1"))
    if MigrationContext.configure(connection).get_current_heads() != (SCHEMA_HEAD,):
        raise RuntimeError("Database schema is not current. Run python -m scripts.migrate upgrade.")
