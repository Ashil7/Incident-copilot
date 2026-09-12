# Milestone 2.5: consistent errors and observability

Verified on 2026-09-12. The user reported 165 tests passed in WSL, and both
rebuilt Docker services are healthy. Live verification passed liveness,
readiness, unique request IDs, 401/404/422 envelopes, and upload-to-audit
correlation. Reviewed application JSON logs show the upload and completed
analysis share request ID `a9a8fcad-9aab-4a3e-bceb-fb1d659e738d`.
The supplied entries contain no credentials or raw uploaded content.
The smoke test retained synthetic incident `dda404ed-b50e-4fa9-ad19-3dfaf354e42b`.
Local Windows verification: Ruff formatting and linting passed; Pytest reported
165 passed with two dependency deprecation warnings.
No migration or dependency change is needed; the schema stays at
`0003_storage_cleanup`. The assistant has not read or modified `.env` credentials.

## Error contract

All application HTTP errors now use this shape instead of the earlier detail field:

```json
{
  "error": {
    "code": "INCIDENT_NOT_FOUND",
    "message": "Incident not found.",
    "request_id": "server-generated-uuid"
  }
}
```

Status codes retain their meaning: 401 unauthenticated, 403 forbidden, 404 unavailable,
409 conflict, 413 size limit, 422 invalid input, and 503 unavailable dependency.
Known domain messages receive stable codes; other HTTP failures get a safe status-based
code/message. Unrecognized exception details and validation input are never echoed.
Unhandled database errors map to 503; other unexpected errors map to 500, without
tracebacks in the response, including when debug mode is enabled. WWW-Authenticate
headers are preserved for bearer failures. OpenAPI documents the shared error model.

An **exception handler** translates a known exception into an HTTP response. A
**domain error** describes an application condition rather than an implementation
detail. The middleware catches unexpected exceptions before a response starts.
If an error happens after the response was sent, it cannot replace that response;
it emits a safe background-failure event. Existing pipeline failure persistence still
controls the incident's FAILED state. An interrupted streaming response can be closed
but its already-sent status cannot be changed.

## Request IDs and logging

A **request ID** connects a response, audit records, and application events for one
request. Each request gets a new server-generated UUID in X-Request-ID; supplied
client IDs are ignored. It is a correlation value, not an authorization credential.

**Middleware** runs around request processing. The pure ASGI implementation keeps a
ContextVar isolated per request and propagates it through FastAPI's synchronous
thread-pool calls and current in-process background tasks. It resets the context
after completion. Future queue workers will need explicit correlation propagation.
CLI audit actions have no HTTP request ID; historical audit rows remain unchanged.

Application logs are JSON with UTC timestamp, level, event, request_id, and applicable
route template, method, status_code, duration_ms, user_id, incident_id, and error_code.
Unexpected failures also include an exception class name, not its text. Route logs
use templates such as `/api/v1/incidents/{incident_id}` rather than raw request URLs;
unknown routes are labeled unmatched. Only known HTTP methods are logged.

The formatter allowlists event names and fields and does not format arbitrary message
arguments or exception tracebacks. It excludes query strings, headers, cookies, bodies,
filenames, raw logs, prompts, tokens, and passwords. JSON event logs replace Uvicorn's
raw access lines. Uvicorn lifecycle/startup messages may still be plain text.

Request duration measures time until the final response body, excluding subsequent
background work. Analysis events report their own duration. Successful/failed requests
and analysis outcomes are visible as events; there is no Prometheus exporter or
cross-process metrics aggregation in this milestone.

Audit writes keep their existing transaction guarantees and now include the current
request ID. Administrator audit responses expose that ID. No backfill is performed.

## Readiness and worker boundaries

`/health/live` returns 200 while the application can serve requests. `/health` remains
its compatibility alias. Neither queries external systems.

`/health/ready` checks PostgreSQL connectivity, the expected migration revision,
and a small temporary storage write/read probe that is removed on close. A healthy
response remains `{"status":"ok"}`. Failures return 503 with DATABASE_UNAVAILABLE,
SCHEMA_NOT_READY, or STORAGE_UNAVAILABLE. Paths and database details are not returned.
The upload directory is created if absent. This probe checks current access, not
long-term capacity, every existing file, or pending-job completion.

LLM access is not a readiness dependency: healthy/no-evidence processing does not
need model credentials. Redis and Celery do not exist in the current architecture,
so there is no fabricated Redis or worker check. In-process BackgroundTasks has no
separate worker heartbeat and remains vulnerable to process interruption. Redis
readiness and durable-worker monitoring belong to Phase 3.

## Verification in WSL, one command at a time

Run the standard checks separately:

```bash
python -m ruff format app tests scripts
python -m ruff check app tests scripts
python -m pytest -v --cov=app --cov-report=term-missing
```

Tests cover the new envelope, missing authentication, generic validation, exception
privacy, debug-mode errors, 503 mapping, simultaneous request isolation, request/log/
audit correlation, background failures, and separate database/schema/storage health
failures. Existing API/security/storage tests remain included.

Rebuild on the existing port without any new migration:

```bash
API_PORT=8001 docker compose up --build -d --wait
```

Run the smoke test:

```bash
python -m scripts.verify_observability --admin
```

Enter existing administrator credentials privately. The script checks all health
endpoints, distinct request IDs, 401/404/422 envelopes, and correlation of a synthetic
upload with its audit event. It leaves one synthetic healthy incident and logs out
its refresh token. Without --admin it checks only health and public error behavior.
Share only the PASS output and request ID, never the login response or password.

Inspect recent application events:

```bash
docker compose logs --tail=40 api
```

Expect JSON request.completed and analysis.completed events with matching request
IDs for the test upload. Readiness probes also produce request events. Use the upload
ID printed by the smoke script to identify its audit/log entries. Routine health
checks are not suppressed or sampled yet.

For direct WSL development, use:

```bash
python -m uvicorn app.main:app --reload --no-access-log
```

Stop at Milestone 2.5. Redis/Celery and durable processing start in Milestone 3.1.

Reference: [Starlette middleware and context propagation](https://www.starlette.io/middleware/).
