"""Read-only Celery worker ping; no credentials or broker URL printed."""

import argparse
import socket

from app.config import Settings
from app.container import container_settings
from app.task_queue import create_celery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", action="store_true")
    args = parser.parse_args()
    application = None
    try:
        settings = Settings()
        if args.container:
            settings = container_settings(settings)
        application = create_celery(settings)
        destination = [f"incident-worker@{socket.gethostname()}"] if args.container else None
        replies = application.control.ping(destination=destination, timeout=3)
        if not any(value.get("ok") == "pong" for reply in replies for value in reply.values()):
            raise RuntimeError("No worker replied")
        print("PASS: Celery worker responded.")
    except Exception:
        print("Worker readiness failed. Check Redis and worker availability.")
        raise SystemExit(1) from None
    finally:
        if application is not None:
            application.close()


if __name__ == "__main__":
    main()
