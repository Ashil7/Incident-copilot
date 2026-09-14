from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models import Incident, User, UserRole
from scripts.seed_demo import CASES, seed_demo

ROOT = Path(__file__).resolve().parents[1]


def test_demo_seed_is_idempotent():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            User(
                email="demo@example.com",
                full_name="Synthetic Demo",
                password_hash="unused-synthetic-hash",
                role=UserRole.ANALYST,
            )
        )
        session.commit()
        assert seed_demo(session, " DEMO@example.com ") == (len(CASES), 0)
        assert seed_demo(session, "demo@example.com") == (0, len(CASES))
        incidents = session.scalars(select(Incident)).all()
        assert len(incidents) == len(CASES)
        assert all(item.confirmed_root_cause for item in incidents)


def test_release_assets_are_hardened_and_documented():
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    production = (ROOT / "docker-compose.production.yml").read_text()
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()

    assert "USER incident" in dockerfile
    assert "FROM python:3.12-slim AS builder" in dockerfile
    assert "no-new-privileges:true" in compose
    assert "cap_drop:" in compose and "read_only: true" in compose
    assert "!reset []" in production and "nginx:1.27-alpine" in production
    assert "python -m scripts.verify_migrations" in workflow
    assert "--cov=app" in workflow and "docker build --check" in workflow
    for relative in (
        "SECURITY.md",
        "docs/architecture.md",
        "docs/deployment.md",
        "docs/interview-guide.md",
        "docs/screenshots/README.md",
    ):
        assert (ROOT / relative).is_file()
