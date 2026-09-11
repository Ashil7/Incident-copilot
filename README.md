# AI Incident & Log Analysis Copilot

## Current checkpoint: Phase 1, Milestone 1.1

The project is following the new end-to-end milestone plan. Milestone 1.1 provides
the FastAPI application, typed settings, `/health`, Swagger/OpenAPI, Ruff
configuration, and a Pytest test skeleton with working foundation tests.
Verified in WSL on Python 3.12.3: Ruff formatting reported 13 files unchanged,
Ruff lint passed, and `pytest -v` reported 12 passed with two dependency deprecation
warnings (Starlette's HTTPX integration and AnyIO's BlockingPortal alias).
Live Uvicorn/browser verification for this milestone remains pending.

Python extracts and measures facts; the planned LLM explains evidence and proposes
investigation steps. A human confirms the cause and resolution. Use synthetic data.

| Capability | Current state |
| --- | --- |
| Settings, health, Swagger | Verified through in-process tests; live browser check pending |
| Ruff and foundation tests | Ruff passed; 12 tests passed in WSL |
| Earlier database implementation | Preserved, disconnected from the default app |
| Uploads, parsing, statistics, LLM analysis | Planned for subsequent milestones |
| Auth, workers, RAG, dashboard, deployment | Planned for later phases |

### Current files

- `app/main.py`: application construction; no database startup.
- `app/config.py`: typed environment settings.
- `app/routers/health.py`: health route and Pydantic response.
- `app/legacy_main.py`: preserved earlier database application entry point.
- `requirements.txt`: application dependencies, including earlier database packages.
- `requirements-dev.txt`: application dependencies plus Ruff, Pytest, coverage, HTTPX.
- `pyproject.toml`: Ruff, Pytest, and foundation coverage configuration.
- `tests/conftest.py`: isolated settings and reusable test client.
- `tests/test_health.py`, `tests/test_config.py`: foundation verification.

The database models, Compose file, and database verification script remain intact.
They are not part of Milestone 1.1 verification. The original database startup
can be accessed through `app.legacy_main:app` when returning to that work.

### WSL setup and verification

Confirmed environment: Python 3.12.3, project `/mnt/d/python/incident-copilot`,
interpreter `.venv-wsl/bin/python3`. Use a Linux virtual environment in WSL;
Windows `Scripts/python.exe` environments cannot be reused as Linux environments.
For a fresh environment, create it with `python3.12 -m venv .venv-wsl`, then
activate it with `source .venv-wsl/bin/activate`. The user's environment is already active.

These commands are a reference. In the guided session, run only the single command
requested by the assistant, share its output, and wait before proceeding.

Install dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Format source files (formatting only):

```bash
python -m ruff format app tests scripts
```

Check formatting:

```bash
python -m ruff format --check app tests scripts
```

Lint for common errors and import ordering:

```bash
python -m ruff check app tests scripts
```

Run tests with foundation coverage:

```bash
python -m pytest --cov --cov-report=term-missing
```

Expected: formatting and lint checks succeed, and all tests pass. Tests use an
in-process HTTPX/TestClient transport and synthetic settings; no PostgreSQL,
Docker, LLM credentials, API credits, or live network access is required.
Coverage currently measures only the Milestone 1.1 application modules.

Start the application:

```bash
python -m uvicorn app.main:app --reload
```

Expected: `Application startup complete` at `http://127.0.0.1:8000`.
`app.main:app` means import the `app.main` module and serve its `app` object.
`--reload` restarts the development server when source files change. Stop with Ctrl+C.

Manual check in another WSL terminal:

```bash
curl -i http://127.0.0.1:8000/health
```

Expect HTTP 200 with `{"status":"ok"}`. Open `http://localhost:8000/docs`,
expand **GET /health**, choose **Try it out**, then **Execute**. Expect the same
result. Swagger's browser assets load from a CDN; rendering the interactive UI
needs internet access. `/openapi.json` is generated locally.

### Settings and beginner concepts

| Setting | Default | Purpose |
| --- | --- | --- |
| `APP_NAME` | `AI Incident Copilot` | Application title in Swagger |
| `APP_ENV` | `development` | Validated label: development, test, or production |
| `DEBUG` | `false` | FastAPI debugging flag; leave false outside local development |
| `DATABASE_URL` | blank | Preserved legacy setting; unused by the current app |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | blank | Preserved future integration settings |
| `UPLOAD_DIRECTORY`, `MAX_UPLOAD_SIZE_MB` | uploads, 5 | Preserved future upload settings |

`.env` is optional for this milestone. Preserve an existing file; on a fresh clone
you may copy `.env.example` to `.env`. Environment variables override file values.
`APP_ENV` is currently just a label, not a complete production-security configuration.
Never commit `.env`, uploaded files, private keys, or virtual environments.

**FastAPI** is the web application framework. **Uvicorn** is the ASGI server that
accepts browser/HTTP requests and passes them to the app. **APIRouter** groups URL
handlers, similar to Django URL patterns. `@router.get("/health")` connects a GET
request to the `health` function; `include_router` registers that group.

**Pydantic** describes and validates data, comparable to a small DRF serializer.
`HealthResponse` defines the JSON response contract. **Pydantic Settings** reads
environment values and validates Python types, similar to typed Django settings.
`SecretStr` masks representations; it is not encryption. Settings are never
returned by `/health`.

**Swagger UI** is an interactive client built from FastAPI's **OpenAPI** schema,
which describes the API for tools. A normal `def` endpoint is suitable here;
FastAPI runs synchronous endpoint functions in a thread pool. You do not need
`async def` for every endpoint.

**Pytest fixtures** supply reusable setup such as a test client. **TestClient**
exercises requests in process without a listening server. **Ruff linting** finds
common code errors; **Ruff formatting** makes whitespace and layout consistent.

```mermaid
flowchart LR
    Client --> Uvicorn --> FastAPI --> HealthRouter
    HealthRouter --> JSON["200: status ok"]
    Config["Environment / optional .env"] --> Settings --> FastAPI
```

### Milestone boundaries and interview practice

The current health endpoint reports liveness, not dependency readiness. No database
tables are created by `app.main`. Authentication, production hardening, migrations,
workers, upload APIs, and AI features are not implemented in this milestone.
Stop after verification; Milestone 1.2 requires an explicit request.

Suggested commit: `feat: establish milestone 1.1 foundation with Ruff and tests`

1. **What does Uvicorn do?** It accepts HTTP requests and runs the FastAPI ASGI app.
2. **What is an APIRouter?** A group of endpoint handlers registered on the application.
3. **How is Pydantic like a DRF serializer?** Both describe and validate data contracts.
4. **Why use environment settings?** Configuration varies between environments without
   hardcoding credentials; typed settings reject invalid values early.
5. **Why use TestClient?** It tests the real application routing and responses in process,
   without starting a server or contacting external services.

References: [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/),
[Ruff configuration](https://docs.astral.sh/ruff/configuration/), and
[Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

---

## Historical Day 2 notes (preserved, not current setup instructions)

The section below records the previous plan and its previous verification results.
Its database startup commands refer to `app.legacy_main:app` now, rather than
`app.main:app`. Follow the Milestone 1.1 instructions above for the current work.

Days 1–2 implement the FastAPI foundation and PostgreSQL persistence. The planned application helps investigate
synthetic application logs: **Python detects and calculates facts; the LLM explains
those facts and suggests investigation steps.** Upload APIs and analysis are still
scheduled for later days. Compose currently runs PostgreSQL only.

What was added:

- `app/main.py`: FastAPI application assembly.
- `app/routers/health.py`: typed `/health` endpoint.
- `app/config.py`: `pydantic-settings` configuration for environment variables.
- `requirements.txt`, `.env.example`, and `.gitignore`.
- `app/database.py`: engine, session factory, declarative base, and `get_db`.
- `app/models.py`: Incident table and environment/status enums.
- `app/schemas.py`: public incident response without internal file paths.
- `docker-compose.yml`: PostgreSQL 16, readiness check, and persistent volume.
- `scripts/verify_database.py`: synthetic database round-trip verification.

Quick start (from project root):

1. Create and activate a virtual environment (example using venv):

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```bash
python -m pip install -r requirements.txt
cp .env.example .env  # fresh clone only; preserve an existing .env
```

3. Configure `.env`: set `POSTGRES_PASSWORD` and a matching `DATABASE_URL`, for
example `postgresql+psycopg://incident_user:YOUR_PASSWORD@localhost:5432/incident_db`.
Replace the placeholder; URL-encode special characters in the URL password.
The existing workspace `.env` was configured with a generated local password.
Start Docker Desktop, then start PostgreSQL:

```bash
docker compose up -d --wait db
docker compose ps
```

Expect the `db` service to be healthy. Run the app with Uvicorn:

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

4. Verify health:

```bash
curl -sS http://127.0.0.1:8000/health
# expected: {"status":"ok"}
```

Swagger UI is available at `http://127.0.0.1:8000/docs`.

If PowerShell blocks activation, use `.venv\Scripts\python.exe` instead of
`python` in the run command. In this workspace, Day 2 uses a clean `.venv-312`
because the existing `.venv` had mismatched Python versions. Use
`.venv-312\Scripts\python.exe` for the commands below, or activate
`.venv-312\Scripts\Activate.ps1`. Local PostgreSQL uses port 55432 in `.env`
because Windows rejected the original 5432 binding.
For a fresh clone, install Python 3.12 first. A uv-created environment may not
include pip; use `python -m ensurepip` before installing dependencies in that case.

For WSL, create a separate Linux environment (do not reuse the Windows `.venv`):

```bash
python3.12 -m venv .venv-wsl
source .venv-wsl/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env  # only if .env does not already exist
# Set POSTGRES_PASSWORD and DATABASE_URL as described above.
docker compose up -d --wait db
python -m uvicorn app.main:app --reload
```

Expected startup: Uvicorn reports `Application startup complete` and listens on
port 8000. Stop with Ctrl+C. Reload is for local development.

## Configuration

Settings read the project-root `.env` regardless of the working directory.
Environment variables override `.env`; restart after editing configuration.
Never commit `.env`. PostgreSQL is required at startup; LLM settings remain unused.

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | required | PostgreSQL URL using `postgresql+psycopg://` |
| `POSTGRES_USER` | example: `incident_user` | Compose database user |
| `POSTGRES_PASSWORD` | required | Compose database password |
| `POSTGRES_DB` | example: `incident_db` | Compose database name |
| `POSTGRES_PORT` | `5432` | Local published port; match this in `DATABASE_URL` |
| `OPENAI_API_KEY` | blank | Secret API key, needed when LLM analysis is added |
| `OPENAI_MODEL` | blank | Explicit model selection when LLM analysis is added |
| `UPLOAD_DIRECTORY` | `uploads` | Future upload location, relative to working directory |
| `MAX_UPLOAD_SIZE_MB` | `5` | Positive integer for the future upload limit |

No model credentials are needed today. Secrets use `SecretStr` to
mask their representation; this is not encryption. Settings are never returned
by the health endpoint. A nonpositive or noninteger upload limit fails startup.

## Day 1 structure and concepts

```text
app/
  __init__.py
  main.py
  config.py
  database.py
  models.py
  schemas.py
  routers/
    __init__.py
    health.py
  services/__init__.py
tests/.gitkeep
uploads/.gitkeep
.env.example
.gitignore
.python-version
requirements.txt
docker-compose.yml
scripts/verify_database.py
README.md
```

`FastAPI` is the application object. `APIRouter` groups related endpoints, much
like a Django app's `urls.py`. The `@router.get` decorator connects an HTTP method
and URL to a Python function, combining URL registration with the view definition.
`include_router` registers that group with the application.

Pydantic's `HealthResponse` describes and validates the response, similar to a
small DRF serializer. `BaseSettings` validates configuration from external values,
adding typed validation to the role served by Django settings. Uvicorn is the
ASGI server that accepts requests and runs the application. In `app.main:app`,
the left side is the Python module and the right side is its application object.

```mermaid
flowchart LR
    Client --> Uvicorn --> FastAPI --> HealthRouter
    HealthRouter --> JSON["200: status ok"]
    Environment["Environment / .env"] --> Settings --> FastAPI
```

## Verification and manual test

In a second PowerShell terminal:

```powershell
curl.exe -i http://127.0.0.1:8000/health
curl.exe -I http://127.0.0.1:8000/docs
```

The health request must return HTTP 200 and `{"status":"ok"}`. Docs should
return HTTP 200. Open `/docs`, expand **GET /health**, click **Try it out**, then
**Execute**; expect the same JSON and status. Swagger UI is an interactive client
generated from the API's OpenAPI description at `/openapi.json`. Its browser assets
load from a CDN, so the interactive page needs internet access.

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Application liveness only |
| `GET /docs` | Swagger UI |
| `GET /openapi.json` | Machine-readable API schema |

Today uses live HTTP and PostgreSQL smoke checks. Parser/redactor Pytest coverage comes in later
days. Health does not verify database connectivity or LLM availability.

## Next days and boundaries

Day 2 adds PostgreSQL/SQLAlchemy. Next: Day 3 uploads, Day 4 redaction/parsing,
Day 5 statistics/evidence, Day 6 LLM/background processing, and Day 7 completes
tests, Docker, and documentation. Use synthetic logs only. Week 1 excludes
authentication, multi-tenancy, a frontend, live streaming, and automatic remediation.
The planned analysis provides possible causes, never confirmed root causes.

Suggested commit: `feat: add Day 2 PostgreSQL persistence and incident model`

Interview questions:

1. What is the difference between a SQLAlchemy engine, session factory, and session?
2. How does a FastAPI dependency using `yield` guarantee session cleanup?
3. Why is `create_all` insufficient for evolving a production database schema?

## Day 2 concepts and verification

The **engine** owns the connection pool. The **session factory** creates sessions;
each **session** tracks ORM changes and manages a transaction. `flush()` sends
pending SQL, `commit()` makes changes durable, and `rollback()` discards pending
transaction changes. Unlike Django's common autocommit workflow, callers explicitly
commit here. `get_db` will supply a session via `Depends(get_db)` in Day 3 routes.
FastAPI runs the dependency before the endpoint and resumes it after `yield` to
close the session, including on failure. The dependency does not commit for callers.

`Base` collects table definitions, similar to Django's model registry. `Incident`
is the database model; `IncidentResponse` is the public contract, similar to a DRF
serializer. `from_attributes=True` lets Pydantic read ORM attributes. Internal
`stored_file_path` is omitted. File metadata is nullable to represent `CREATED`
incidents before uploads are introduced; timestamps use timezone-aware UTC.

FastAPI's **lifespan** context runs before serving requests and during shutdown.
Startup creates missing tables and proves database connectivity; shutdown disposes
the engine. No connection is opened just by importing the database module.
`create_all` is a learning shortcut: it does not migrate existing columns or enum
values. Use Alembic after Week 1. Startup fails if PostgreSQL is unavailable.
`GET /health` remains a liveness check and does not query PostgreSQL on each request.

With the API running, execute in a second terminal:

```powershell
.\.venv-312\Scripts\python.exe -m scripts.verify_database
curl.exe -i http://127.0.0.1:8000/health
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'
```

Expect `PASS` from the verification script, HTTP 200 with `{"status":"ok"}`,
and an `incidents` table. The script checks a synthetic insert/read, UUID generation,
defaults, timezone-aware timestamps, JSON storage, response privacy, and rollback.
It leaves no incident behind. In WSL use `python -m scripts.verify_database`.
Manual test: restart Uvicorn, rerun these commands, and confirm existing tables
remain usable. Swagger still exposes only `/health`; incident routes arrive Day 3.

PostgreSQL data persists in a named volume. `docker compose stop db` stops the
database while retaining data. PostgreSQL initialization variables apply only to
an empty volume; editing `.env` does not change an existing database password.
The published port binds to loopback. For a local/WSL API use `localhost`; the
future Compose API service will use `db` as its database hostname. If port 5432
is occupied, select another `POSTGRES_PORT` and update `DATABASE_URL` to match.
API containerization is deferred to Day 7.

Further reading: [SQLAlchemy sessions](https://docs.sqlalchemy.org/en/20/orm/session_basics.html),
[FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), and
[Compose readiness](https://docs.docker.com/compose/how-tos/startup-order/).

Verified locally on Python 3.12.2: Compose reports PostgreSQL healthy; application
startup creates the table; the database verification script passes; `/health`,
`/docs`, and `/openapi.json` return 200. The verification API is running on port
8001, so use `http://127.0.0.1:8001/docs` for that process. To run it again:

```powershell
.\.venv-312\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
```

References: [FastAPI first steps](https://fastapi.tiangolo.com/tutorial/first-steps/)
and [Pydantic settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).
