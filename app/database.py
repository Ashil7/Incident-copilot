"""Synchronous SQLAlchemy connections and request-scoped sessions."""

from collections.abc import Generator

from fastapi import Request
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings


class Base(DeclarativeBase):
    """Shared table metadata for ORM models."""


def create_database_engine(settings: Settings) -> Engine:
    if not settings.database_url.get_secret_value():
        raise RuntimeError("DATABASE_URL is required to start the database-backed application.")
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_timeout=5,
        connect_args={"connect_timeout": 5},
        hide_parameters=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db(request: Request) -> Generator[Session, None, None]:
    """Provide one session per request, closing it even if the request fails."""
    with request.app.state.session_factory() as session:
        yield session
