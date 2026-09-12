"""Create the first administrator locally; never promotes a public registration."""

from getpass import getpass

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.auth_schemas import RegisterRequest
from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.models import User, UserRole
from app.services.audit import record_event
from app.services.auth import password_hasher


class BootstrapError(RuntimeError):
    """A controlled message that contains no supplied credentials."""


def failure_reason(error: Exception) -> str:
    if isinstance(error, BootstrapError):
        return str(error)
    if isinstance(error, ValidationError):
        fields = {item["loc"][0] for item in error.errors() if item["loc"]}
        reasons = []
        for field, message in (
            ("email", "Enter a valid email address."),
            ("full_name", "Full name must contain 1–200 characters and cannot be blank."),
            ("password", "Password must contain 12–128 characters."),
        ):
            if field in fields:
                reasons.append(message)
        return " ".join(reasons) or "Application configuration is invalid."
    if isinstance(error, SQLAlchemyError):
        code = getattr(getattr(error, "orig", None), "sqlstate", None)
        return {
            "23505": "A unique value already exists; no account was created.",
            "23514": "Database constraint rejected the account; check schema compatibility.",
            "42P01": "A required table is missing; check the database migration revision.",
            "42501": "The database role lacks permission for this operation.",
            "28P01": "Database authentication failed.",
        }.get(code, "Database operation failed; check connectivity and schema compatibility.")
    return "Unexpected setup failure; no credentials printed."


def create_first_admin(session, payload: RegisterRequest) -> str:
    if session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(2301001)"))
    if session.scalar(select(User.id).where(User.role == UserRole.ADMIN)) is not None:
        raise BootstrapError("An administrator already exists; use administrator user management.")
    if session.scalar(select(User.id).where(User.email == str(payload.email))) is not None:
        raise BootstrapError("Email already exists; no account was changed.")
    user = User(
        email=str(payload.email),
        full_name=payload.full_name,
        password_hash=password_hasher.hash(payload.password.get_secret_value()),
        role=UserRole.ADMIN,
        is_active=True,
    )
    session.add(user)
    session.flush()
    record_event(session, user.id, "admin.bootstrapped", "user", user.id)
    return user.id


def main() -> None:
    engine = None
    try:
        email = input("New administrator email: ")
        name = input("Full name: ")
        password = getpass("Password (12–128 characters, hidden): ")
        if password != getpass("Repeat password: "):
            print("Passwords do not match; no account was created.")
            return
        payload = RegisterRequest(email=email, full_name=name, password=password)
        engine = create_database_engine(Settings())
        with create_session_factory(engine).begin() as session:
            create_first_admin(session, payload)
        print("Administrator created. No credentials printed.")
    except Exception as error:
        print("Administrator creation failed:", failure_reason(error))
        raise SystemExit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
