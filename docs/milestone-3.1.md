# Milestone 3.1: Redis and Celery

Verified on 2026-09-12. The user reported 176 tests passed in WSL. All four Docker
services became healthy and the worker ping passed. A synthetic upload stayed
UPLOADED while the worker was stopped, then completed with persisted analysis
after the worker restarted. Reviewed worker.started and analysis.completed logs
matched upload request ID `93c7763c-0922-43ef-a2b9-c002f6f8673a` and retained incident
`7b7cd658-38f2-46d1-8cd6-e341d4135620`.
Live file checks passed multiple uploads, SHA-256, private metadata, combined
analysis, attachment, deletion, and empty state. That test retained empty incident
`738321b7-ef58-4ce2-91b3-c09bedffda9b`. These checks do not establish crash recovery
or exactly-once delivery; the limits below still apply.
Local Windows checks passed: Ruff formatting, Ruff linting, and 176 tests with
the same two dependency deprecation warnings. Celery worker CLI options were
also checked without connecting to external services.
No database migration is required; schema remains `0003_storage_cleanup`.
The existing `.env` credentials are unchanged.

## What changed

The API saves uploads and commits database metadata, then publishes a small JSON
message to Redis. A separate Celery worker reads that message and runs the existing
analysis pipeline. File attachment and deletion also use the queue, including
deferred storage cleanup. FastAPI no longer runs production analysis through
`BackgroundTasks`.

Redis is the **broker**: it holds waiting messages. Celery is the task framework;
the **worker** is a separate process that consumes them. A message contains only
an incident UUID, request UUID, and processing flags. It contains no database
credentials, tokens, file paths, or uploaded text. The worker opens its own engine
and sessions and disposes them after each task. PostgreSQL remains the source of
incident status/results, so no Celery result backend is needed.

The synchronous FastAPI routes run in FastAPI's thread pool. They wait for queue
publication, not analysis completion. A successful upload still returns HTTP 202.
The worker receives the original request ID and includes it in application JSON
logs. Ordinary Celery log messages are reduced to safe generic events; the startup
banner is suppressed to avoid displaying connection configuration.

Both API and worker mount the same `upload_data` volume at `/app/uploads`. This
preserves storage scope and lets the worker verify and read API-created files.
Compose adds Redis with an append-only log in `redis_data`; it does not remove
existing PostgreSQL or upload volumes.

## Readiness and limits

`/health/live` remains independent of dependencies. `/health/ready` checks database
connectivity/schema, storage, and Redis PING. It does not claim a worker is online.
The worker has a separate, destination-specific Celery ping health check. The API
can accept queued work while a worker is stopped.

This milestone moves processing across processes; it is not an exactly-once or
fully recoverable pipeline. Existing conditional incident claims prevent simultaneous
processing of the same UPLOADED incident. Celery acknowledges tasks before execution
because interrupted stage recovery is not implemented yet. A killed worker can
leave an incident in a processing state. Automatic retries, staged recovery, and
duplicate-job management belong to Milestone 3.2.

PostgreSQL commit and Redis publication are separate operations. A process crash
between them can leave a saved UPLOADED incident without a message. A publish error
returns `QUEUE_UNAVAILABLE` (503), preserves committed files/metadata, and logs a
safe event. Delivery may be ambiguous, so inspect the incident list before repeating
an upload. There is no automatic republisher or transactional outbox yet. Deletion
cleanup rows remain available to the existing cleanup command if publication fails.
Redis uses `appendfsync everysec`; a host failure can lose roughly the last second
of queue writes. These limits must not be described as guaranteed delivery.

## Configuration

For WSL API and worker processes, the default `REDIS_URL` is
`redis://localhost:6379/0`. Compose sets `redis://redis:6379/0` for both services.
Redis's host port binds only to `127.0.0.1`, default 6379; `REDIS_PORT` overrides
the host mapping. If changed, update the WSL `REDIS_URL` port to match. Compose
containers still use the internal port 6379. This local Redis setup has no password;
do not publish it to a public interface.

PostgreSQL remains `localhost:5433` from WSL and `db:5432` in Compose. API port 8001
still avoids the existing host conflict. No `.env` edits are necessary with defaults.

For direct WSL development, start `db` and `redis` in Compose, then run the API and
`python -m app.worker` in separate activated WSL terminals. Both processes must
use the same upload directory. Do not mix a WSL worker with a Docker API's separate
upload volume. Docker is the recommended verification setup below.

## Verification, one command at a time

Install the changed requirements in `.venv-wsl` (already reported installed):

```bash
python -m pip install -r requirements-dev.txt
```

Run each check and wait for its result:

```bash
python -m ruff format app tests scripts
```

```bash
python -m ruff check app tests scripts
```

```bash
python -m pytest -v
```

Offline route tests use an explicitly injected test queue. Queue contract tests
check commit-before-publish, no inline execution, failure preservation, JSON
payloads, readiness, worker-owned connections, and request context cleanup.
They do not prove real Redis delivery; use the following live checks for that.

```bash
API_PORT=8001 docker compose up --build -d --wait
```

Expect API, database, Redis, and worker healthy. Verify the worker:

```bash
docker compose exec worker python -m scripts.verify_worker --container
```

For the queued-work check, stop only the worker:

```bash
docker compose stop worker
```

Submit one synthetic upload using existing account credentials, entered privately:

```bash
python -m scripts.verify_queue --expect-queued
```

Expect PASS and retain the incident ID printed by the script. Start the worker:

```bash
API_PORT=8001 docker compose up -d --wait worker
```

Use that ID in the next command (replace `INCIDENT_ID`):

```bash
python -m scripts.verify_queue --incident INCIDENT_ID
```

Expect completed deterministic analysis without an LLM key. The synthetic incident
is retained and refresh tokens used by the script are logged out. Inspect logs:

```bash
docker compose logs --tail=40 worker
```

Expect `worker.started` and `analysis.completed` with the original upload request
ID and incident ID. Existing `python -m scripts.verify_files` can then verify queued
attachment and deletion behavior. Stop after Milestone 3.1.

Reference: [Celery configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html).
