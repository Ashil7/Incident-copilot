"""Alembic environment; configuration stays out of alembic.ini and logs."""

from alembic import context

from app import models  # noqa: F401 -- Register model metadata for schema comparison.
from app.config import Settings
from app.database import Base, create_database_engine


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Use connected migrations; legacy adoption requires schema inspection.")
elif (connection := context.config.attributes.get("connection")) is not None:
    run(connection)
else:
    engine = create_database_engine(Settings())
    try:
        with engine.connect() as connection:
            run(connection)
    finally:
        engine.dispose()
