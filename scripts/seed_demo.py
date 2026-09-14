"""Create idempotent synthetic portfolio incidents for an existing local account."""

import argparse
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.models import Environment, Incident, IncidentStatus, User

CASES = (
    (
        "Demo: upstream order timeout",
        "orders-api",
        "HTTP_FAILURE",
        "Synthetic order requests returned upstream timeouts.",
        "Synthetic dependency connection pool exhaustion",
        "Raised the synthetic pool limit after review",
    ),
    (
        "Demo: authentication errors",
        "identity-api",
        "AUTHENTICATION_FAILURE",
        "Synthetic login requests returned HTTP 401.",
        "Synthetic signing-key mismatch",
        "Aligned the synthetic signing configuration",
    ),
)


def seed_demo(session, email: str) -> tuple[int, int]:
    """Create the synthetic portfolio rows and return created/existing counts."""
    user = session.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        raise RuntimeError("Account not found.")
    created = 0
    for title, service, kind, summary, cause, resolution in CASES:
        if session.scalar(
            select(Incident.id).where(Incident.owner_user_id == user.id, Incident.title == title)
        ):
            continue
        now = datetime.now(timezone.utc)
        session.add(
            Incident(
                owner_user_id=user.id,
                title=title,
                service_name=service,
                environment=Environment.DEV,
                status=IncidentStatus.COMPLETED,
                severity="MEDIUM",
                statistics={"total_events": 3, "error_count": 2, "evidence": []},
                analysis={
                    "provider": "deterministic-demo",
                    "result": {
                        "incident_type": kind,
                        "summary": summary,
                        "possible_causes": [],
                        "recommended_checks": [],
                        "information_gaps": ["Synthetic demonstration only."],
                    },
                },
                confirmed_root_cause=cause,
                resolution_notes=resolution,
                completed_at=now,
            )
        )
        created += 1
    session.commit()
    return created, len(CASES) - created


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Existing local account owner")
    args = parser.parse_args()
    engine = create_database_engine(Settings())
    try:
        with create_session_factory(engine)() as session:
            created, existing = seed_demo(session, args.email)
        print(f"PASS: synthetic demo ready; created {created}, existing {existing}.")
    except Exception:
        print("Demo seed failed. Check the account and database; no credentials displayed.")
        raise SystemExit(1) from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
