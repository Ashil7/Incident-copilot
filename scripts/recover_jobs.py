"""Republish unfinished durable jobs without resetting state or attempt limits."""

import argparse
from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.config import Settings
from app.container import container_settings
from app.database import create_database_engine, create_session_factory
from app.migration_state import verify_schema
from app.models import AnalysisJob
from app.services.jobs import ACTIVE
from app.task_queue import TaskQueue


def recover(factory, queue, *, limit=100):
    with factory() as session:
        jobs = list(
            session.scalars(
                select(AnalysisJob)
                .where(
                    AnalysisJob.status.in_(ACTIVE),
                    or_(
                        AnalysisJob.retry_at.is_(None),
                        AnalysisJob.retry_at <= datetime.now(timezone.utc),
                    ),
                )
                .order_by(AnalysisJob.created_at, AnalysisJob.id)
                .limit(limit)
            )
        )
    published = 0
    for job in jobs:
        queue.enqueue(
            job.incident_id, job.request_id, analyze=job.analyze, cleanup=job.cleanup, job_id=job.id
        )
        published += 1
    return published


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args()
    engine = queue = None
    try:
        settings = Settings()
        if args.container:
            settings = container_settings(settings)
        engine = create_database_engine(settings)
        with engine.connect() as connection:
            verify_schema(connection)
        queue = TaskQueue(settings)
        print("Jobs republished:", recover(create_session_factory(engine), queue))
    except Exception:
        print("Recovery did not finish. Jobs remain durable; check database and Redis readiness.")
        raise SystemExit(1) from None
    finally:
        if queue:
            queue.close()
        if engine:
            engine.dispose()


if __name__ == "__main__":
    main()
