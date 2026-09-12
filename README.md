# AI Incident & Log Analysis Copilot

Current checkpoint: **Milestone 2.5 — verified on 2026-09-12**.
See [the milestone guide](docs/milestone-2.5.md).
Local Ruff checks passed, and Pytest reported 165 passed with two dependency warnings.
The user reported 165 tests passed in WSL. Both Docker services are healthy.
Live verification passed liveness, readiness, unique request IDs, 401/404/422
error envelopes, and upload-to-audit correlation. Reviewed JSON logs confirm
the upload and background analysis share the same request ID; no credentials
or raw uploaded content appear in the supplied application log entries.
Error responses now use the `error.code`, `error.message`, `error.request_id` envelope.
No migration or new dependency is required; `.env` is unchanged.

Previous checkpoint: **Milestone 2.4 — verified**.
The user reported checks passed and 153 tests passed in WSL. PostgreSQL migration
verification passed, and the database was upgraded to `0003_storage_cleanup`.
Both Docker services are healthy. Live tests passed multiple uploads, SHA-256,
metadata privacy, combined analysis, attachment, deletion, and final empty state.
Cleanup processed zero additional objects, and the pending-deletion count was zero.
See [the Milestone 2.4 guide](docs/milestone-2.4.md).

Previous checkpoint: **Milestone 2.3 — verified on 2026-09-12**.
WSL reported 136 tests passed with 96% coverage and two dependency warnings.
The later bootstrap diagnostic fix passed Ruff and 15 targeted tests locally.
Both Docker services are healthy. Live checks passed authenticated uploads,
owner access, cross-user isolation, anonymous rejection, administrator access,
user listing, and creation auditing. Analysts see their own records; administrators
can also see legacy ownerless incidents. See [the milestone guide](docs/milestone-2.3.md).
No new migration or dependency was required for Milestone 2.3.

Previous checkpoint: **Milestone 2.2 — authentication verified on 2026-09-12**.
Ruff passed in WSL, and the user reported all tests passed. Local Windows verification
recorded 124 tests passed with two dependency warnings. Both rebuilt Docker services
are healthy on the existing setup, with the API on port 8001. The live authentication
smoke test passed registration, login, me, refresh rotation, replay rejection, and
logout without printing credentials. The user configured a private signing key and
enabled local registration. See [the authentication guide](docs/milestone-2.2.md).
The database revision remains `0002_normalized`.

Previous checkpoint: **Phase 2, Milestone 2.1 — verified on 2026-09-12**.
WSL Python 3.12.3: Ruff passed; 102 tests passed with 97% coverage and two dependency
deprecation warnings. PostgreSQL migration tests passed, and the user upgraded the
application database to `0002_normalized`. Database verification, Docker health,
readiness, preservation of the previous incident, and a fresh upload completing with
deterministic analysis all passed on port 8001. `.env` is unchanged. See
[the migration guide](docs/milestone-2.1.md) for setup and verification details.
Milestone 2.1 did not include authentication.

Previous checkpoint — Phase 1, Milestone 1.7 verified on 2026-09-12:
Ruff formatting and lint passed; WSL Python 3.12.3 reported 96 tests passed,
97% coverage, and two warnings. The Docker image built successfully, both services
became healthy, and readiness returned HTTP 200. A synthetic upload returned 202
and its detail returned 200 with COMPLETED status and deterministic analysis.
Milestone 1.6 also verified controlled failure without LLM credentials. Real provider
success has not been verified. Historical milestone notes are in
[docs/milestone-history.md](docs/milestone-history.md); use this guide for current setup.

This learning application accepts synthetic UTF-8 logs, redacts known patterns,
parses events, calculates statistics, selects evidence, and generates validated
analysis. Possible causes are hypotheses. No evidence does not prove service health.

## Prerequisites and configuration

Use Python 3.12 in WSL and Docker Desktop with integration enabled for your WSL
distribution. Python virtual environments do not control Docker. Keep the Linux
`.venv-wsl` separate from Windows virtual environments.

For a fresh checkout, create the environment and install dependencies:

```bash
python3.12 -m venv .venv-wsl
source .venv-wsl/bin/activate
python -m pip install -r requirements-dev.txt
```

Copy `.env.example` to `.env` only if `.env` does not already exist. Set credentials
privately. Never commit `.env` or paste its contents. Existing users retain their
working configuration.

| Setting | Purpose |
| --- | --- |
| DATABASE_URL | Required `postgresql+psycopg://` URL; WSL uses `localhost:5433` |
| POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB | Database initialization settings; match the URL |
| POSTGRES_PORT | Host port; default `5433`, container port remains `5432` |
| API_PORT | Compose host API port; default `8000` |
| UPLOAD_DIRECTORY | WSL default `uploads`; Compose overrides to `/app/uploads` |
| MAX_UPLOAD_SIZE_MB | Positive upload limit, default `5` |
| MAX_FILES_PER_INCIDENT | File count cap, default `10`, range 1–50 |
| MAX_EVIDENCE_ITEMS | Evidence cap, default `30`, range 1–100 |
| OPENAI_API_KEY | Optional until evidence-bearing model analysis is requested |
| LLM_MODEL | Explicit model ID; OPENAI_MODEL is the compatibility fallback |
| LLM_TIMEOUT_SECONDS | Provider timeout, default `60`, maximum `300` |
| APP_ENV / DEBUG | Application environment and debug flag; Compose disables debug |
| JWT_SECRET_KEY | Required private random signing key, at least 32 bytes; never commit it |
| JWT_ISSUER / JWT_AUDIENCE | Token issuer and intended API; defaults incident-copilot / incident-copilot-api |
| ACCESS_TOKEN_MINUTES | Access lifetime, default 15, range 1–60 |
| REFRESH_TOKEN_DAYS | Refresh lifetime, default 7, range 1–30 |
| ALLOW_REGISTRATION | Defaults false; explicitly enable for the local registration demo |

Settings load the project-root `.env`; environment variables take precedence.
URL-encode special characters in URL credentials. SecretStr masks representations;
it does not encrypt secrets. Changing initialization variables does not change an
existing PostgreSQL role password. Preserve the database volume when troubleshooting.

## Run directly in WSL

From `/mnt/d/python/incident-copilot`, with `.venv-wsl` active:

```bash
docker compose up -d --wait db
python -m scripts.migrate check
python -m scripts.migrate upgrade
python -m uvicorn app.main:app --reload --no-access-log
```

Wait for `Application startup complete`. Use a second terminal for checks.
Stop Uvicorn with Ctrl+C before starting the Compose API on the same port.

## Run API and PostgreSQL in Compose

Milestone 2.1 requires an explicit migration before starting the updated API.
For existing data, complete the migration guide's backup and checks first.
For container-only operation, build with `docker compose build api`, then use
`API_PORT=8001 docker compose run --rm --no-deps api python -m scripts.migrate upgrade --container`
while `db` is healthy. This one-off container publishes no API port. Stop API
writers during migration. Startup checks the revision; it never changes the schema.

Verified local setup: host port 8000 could not be published, so this workspace
uses port **8001** with a temporary override, leaving `.env` unchanged:

```bash
API_PORT=8001 docker compose up --build -d --wait
```

Use `http://127.0.0.1:8001/docs` and replace port 8000 with 8001 in the
manual HTTP checks below when using this Compose setup. Repeat the `API_PORT=8001`
prefix on future Compose `up` commands; the override is not saved in your shell.
PostgreSQL still uses host port 5433 and internal port 5432.

For environments where host port 8000 is available, the default command is:

```bash
docker compose up --build -d --wait
```

The API image installs runtime dependencies on Python 3.12 and runs as an
unprivileged user, with one process and no development reload. `.dockerignore`
limits build inputs to application code, scripts, and requirements; `.env`, local
uploads, virtual environments, and Git history are excluded from the image.
Compose supplies `.env` at runtime. `app.container` changes only the URL host/port
in memory to `db:5432`, preserving credentials and the original file. Do not change
your WSL URL to `db`.

A **Docker image** packages the application and dependencies. A **container** runs
that image. **Compose** starts related services on a shared network, where `db`
is the database hostname. A **healthcheck** reports whether a service is ready;
Compose waits for PostgreSQL before starting the API. A **named volume** keeps data
outside a replaceable container. `postgres_data` preserves the existing database;
`upload_data` stores new container uploads. Existing WSL upload files are not copied
into that volume. Old records remain in the shared database, but stored WSL paths
are not portable into the container. Use fresh synthetic uploads for this demo.

Both published ports bind to loopback. API port 8000 maps to container port 8000;
database host port 5433 maps to container port 5432. To stop while keeping data:

```bash
docker compose stop
```

Do not remove volumes to fix routine startup problems. Avoid running WSL and
Compose API processes simultaneously during verification. Rebuild after code or
requirements changes. Recreate the API after runtime configuration changes.

## API and manual verification

| Endpoint | Behavior |
| --- | --- |
| GET /health or /health/live | Liveness; no external checks |
| GET /health/ready | Database connectivity, migration revision, and storage read/write readiness |
| GET /docs | Interactive Swagger UI |
| GET /openapi.json | API contract |
| POST /api/v1/incidents | Multipart upload; returns 202 and UPLOADED snapshot |
| GET /api/v1/incidents | Paginated list, limit 1–100 and offset |
| GET /api/v1/incidents/{id} | Stored incident and processing status |
| GET /api/v1/incidents/{id}/files | Authorized file metadata; storage keys excluded |
| POST /api/v1/incidents/{id}/files | Attach multipart log_files; 202 schedules combined analysis |
| DELETE /api/v1/incidents/{id}/files/{file_id} | Remove file; 204, retriable storage cleanup |
| POST /api/v1/auth/register | JSON account registration; creates ANALYST only |
| POST /api/v1/auth/login | JSON email/password login; returns bearer and refresh tokens |
| POST /api/v1/auth/refresh | JSON refresh token; atomically rotates it |
| POST /api/v1/auth/logout | JSON refresh token; revokes it, returns 204 |
| GET /api/v1/auth/me | Requires Authorization: Bearer access token |
| GET /api/v1/admin/users | Administrator-only paginated user list |
| PATCH /api/v1/admin/users/{id} | Administrator-only role/active-state changes |
| GET /api/v1/admin/audit-events | Administrator-only paginated audit list |

Incident endpoints require authentication from Milestone 2.3 onward. List filters:
`status`, `environment`, exact `service_name`, `severity`, timezone-aware
`created_from`/`created_to`, and allowlisted `sort`. Existing limit/offset pagination
and JSON-list response shape are preserved. Ownership is applied before pagination.

Every HTTP response includes a server-generated `X-Request-ID`; error bodies include
the same ID. JSON application events and new HTTP-triggered audit rows use it for
correlation. Raw Uvicorn access logging is disabled to avoid query-string logging.
Use `python -m scripts.verify_observability --admin` for the Milestone 2.5 live checks.

Milestone 2.4 accepts the existing `log_file` field or repeated `log_files` fields
on incident creation. Supported logs are UTF-8 `.log`, `.txt`, and `.json` files.
Size and SHA-256 are recorded during streaming. New analyses combine the current
file set. File edits are blocked while processing is queued/running. See the guide
for legacy uploads, cleanup retries, and file-edit behavior.

Run these separately, checking each result before continuing:

```bash
docker compose ps
```

Expect both Compose services healthy. For WSL-only mode, only `db` is a container.

```bash
curl -i http://127.0.0.1:8000/health/ready
```

Expect HTTP 200 and `{"status":"ok"}`. For a WSL database smoke test:

```bash
python -m scripts.verify_database
```

This uses a rolled-back synthetic insert to verify PostgreSQL connectivity, tables,
UUIDs, defaults, UTC timestamps, JSON, response privacy, and rollback. It retains no
incident. Run this from the WSL project environment, whose URL uses localhost:5433.

For a complete authenticated test, use `python -m scripts.verify_permissions --admin`
after the first-admin setup in the milestone guide. For individual curl requests,
set ACCESS_TOKEN privately from a login response; never share it. Upload a synthetic
healthy event (no model call is required):

```bash
printf '2026-09-12T10:00:00Z INFO GET /health 200 10ms\n' | curl -i http://127.0.0.1:8000/api/v1/incidents -H "Authorization: Bearer $ACCESS_TOKEN" -F 'title=Milestone 2.3 smoke test' -F 'log_file=@-;filename=healthy.log;type=text/plain'
```

Expect 202. Substitute the returned ID in the next command:

```bash
curl -i http://127.0.0.1:8000/api/v1/incidents/REPLACE_WITH_ID -H "Authorization: Bearer $ACCESS_TOKEN"
```

Expect eventual COMPLETED with deterministic analysis and no evidence. Poll again
if processing is still underway. An error-bearing upload with missing model settings
ends FAILED with a safe message and preserved statistics/evidence. With configured
credentials, error-bearing uploads can call the provider and incur charges. The
smoke upload remains as a demo record.

## Tests and coverage

With `.venv-wsl` active and development dependencies installed, run one at a time:

```bash
python -m ruff format app tests scripts
python -m ruff check app tests scripts
python -m pytest -v --cov=app --cov-report=term-missing
```

Tests use temporary files and SQLite for fast isolation, and block live provider
calls. Mocked responses test provider integration, schema/citation validation,
stage transitions, output redaction, and safe failures. Additional checkpoint tests
cover container URL preservation, split UTF-8 characters, partial upload cleanup,
and missing stored files. Coverage includes the entire app package; it is not a
substitute for PostgreSQL and Docker smoke checks. No live model compatibility is
claimed. Two previously observed dependency deprecation warnings are separate from
test failures.

## How the backend works

FastAPI maps HTTP requests to Python functions; routers group endpoints. Pydantic
validates settings and response shapes. Uvicorn serves the application. A lifespan
function checks the migration revision at startup and releases the engine at shutdown.

The SQLAlchemy **engine** manages connections. **sessionmaker** creates sessions;
a **session** manages a unit of database work. The declarative **Base** collects
ORM table definitions; an **ORM model** maps Python attributes to columns. Models
are registered by the `app.models` package for Alembic. **get_db** yields
one request-scoped session and closes it afterward. **commit** saves a transaction,
**refresh** reloads database values into an object, and **rollback** discards pending
changes. Alembic now manages schema changes; startup table creation is removed.

An upload is validated and stored under a generated filename, then committed.
FastAPI BackgroundTasks runs processing after the response using its own session:
PARSING → CALCULATING → GENERATING_ANALYSIS → VALIDATING → COMPLETED, or FAILED.
No-evidence results bypass the provider. Only redacted statistics/evidence are sent
to the model. Returned citations must reference selected evidence IDs. Polling the
detail endpoint lets clients observe the saved state.

## Phase 1 boundaries

Use synthetic logs only. Raw uploaded files remain on disk; redaction recognizes
known patterns and is not a guarantee against every secret. Upload size is checked
while copying after framework multipart parsing; this is not a deployment-wide
request quota. Milestone 2.3 enforces user ownership and administrator permissions
on existing incident routes. There is no organization-level tenancy, retention automation,
or automatic remediation. BackgroundTasks is in-process: a crash can strand an
incident, and no durable retry queue is provided. Durable workers belong to later
milestones. Stop at Milestone 2.5 for the current checkpoint. Keep this learning
instance on loopback.

Docker references: [startup order](https://docs.docker.com/compose/how-tos/startup-order/)
and [Dockerfile best practices](https://docs.docker.com/build/building/best-practices/).
