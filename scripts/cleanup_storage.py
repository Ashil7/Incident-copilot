"""Retry committed pending deletions in the selected storage environment."""

import argparse

from app.config import Settings
from app.container import container_settings
from app.database import create_database_engine, create_session_factory
from app.services.incident_files import cleanup_pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args()
    engine = None
    try:
        settings = Settings()
        if args.container:
            settings = container_settings(settings)
        engine = create_database_engine(settings)
        print(
            "Completed pending deletions:",
            cleanup_pending(create_session_factory(engine), settings),
        )
    except Exception:
        print("Cleanup failed. Check database and storage access; no paths or credentials printed.")
        raise SystemExit(1) from None
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
