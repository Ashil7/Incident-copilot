# AI Incident Copilot

AI Incident Copilot is a FastAPI application that turns synthetic application logs
into a structured, evidence-backed incident analysis. It combines deterministic log
processing with optional LLM analysis, background jobs, private runbook retrieval,
similar-incident search, human-confirmed resolutions, and an authenticated web UI.

The project is complete through **Phase 6**. The verified release has **220 passing
tests**, a **90% coverage gate**, checked fresh and legacy PostgreSQL migrations, and
healthy non-root Docker services.

> Use synthetic logs only. AI output contains hypotheses and suggested checks; a human
> must confirm root cause, resolution, and any remediation.

## What it does

- Accepts multiple UTF-8 `.log`, `.txt`, and `.json` files with streaming size limits
  and SHA-256 metadata.
- Redacts recognized secrets before analysis, parses events, calculates statistics,
  groups error signatures, and selects traceable evidence.
- Runs analysis asynchronously through Redis and Celery with persisted progress,
  bounded retries, recovery, and explicit reanalysis.
- Uses a provider-neutral AI interface with validated structured output, evidence
  citations, normalized usage metadata, and deterministic no-evidence behavior.
- Indexes private or global runbooks with pgvector and returns citation-checked answers.
- Finds similar incidents within the authenticated owner's records and stores
  human-confirmed causes, resolutions, and feedback.
- Provides JWT authentication, refresh-token rotation, role-based administration,
  owner isolation, audit records, request IDs, health checks, a browser UI, and RCA PDFs.
- Supports local files by default and optional private S3-compatible object storage.

## Architecture

```mermaid
flowchart LR
    User[Browser or API client] --> API[FastAPI API and UI]
    API --> DB[(PostgreSQL + pgvector)]
    API --> Storage[Local volume or S3]
    API --> Redis[(Redis queue)]
    Redis --> Worker[Celery worker]
    Worker --> Storage
    Worker --> DB
    Worker --> Provider[Optional AI provider]
```

The API validates and persists an upload before publishing a job. The worker opens its
own database session, loads the stored files, and advances the job through parsing,
statistics, evidence selection, analysis, and validation. Only redacted evidence and
statistics may reach the model. Results and job state are persisted so clients can poll
without depending on the worker process.

See [the detailed architecture](docs/architecture.md) for request, retrieval, and
failure flows.

## Technology

| Area | Choice | Reason |
| --- | --- | --- |
| API and UI | FastAPI, Pydantic, Jinja2, Bootstrap | Typed contracts, generated OpenAPI, and a small server-rendered UI |
| Persistence | SQLAlchemy 2.x, Alembic, PostgreSQL 16 | Explicit transactions and reviewable schema evolution |
| Retrieval | pgvector | Vector search stays alongside authorization and incident data |
| Jobs | Celery and Redis | API requests remain responsive while work is retried independently |
| AI | Provider-neutral service with an OpenAI adapter | Provider calls are isolated and outputs are schema-validated |
| Storage | Local volume or S3-compatible backend | Simple local development with a production object-storage path |
| Delivery | Docker Compose, Nginx example, GitHub Actions | Reproducible services and automated release checks |

## Quick start with WSL and Docker Desktop

Requirements: Python 3.12, Docker Desktop with WSL integration, and Git.

```bash
python3.12 -m venv .venv-wsl
source .venv-wsl/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Edit `.env` with private local values. At minimum, set matching PostgreSQL values,
`DATABASE_URL`, and a random `JWT_SECRET_KEY` of at least 32 bytes. Never commit or
paste `.env`. This repository's verified WSL setup uses:

```dotenv
DATABASE_URL=postgresql+psycopg://YOUR_USER:YOUR_URL_ENCODED_PASSWORD@localhost:5433/YOUR_DATABASE
POSTGRES_PORT=5433
API_PORT=8001
```

The PostgreSQL container still listens on port `5432`; `5433` is the Windows/WSL host
port. Start dependencies and apply migrations:

```bash
docker compose up -d --wait db redis
python -m scripts.migrate upgrade
python -m scripts.migrate check
```

Start the complete stack:

```bash
API_PORT=8001 docker compose up --build -d --wait
```

Open the [web UI](http://127.0.0.1:8001/), [Swagger UI](http://127.0.0.1:8001/docs),
or [readiness endpoint](http://127.0.0.1:8001/health/ready).

Create the first administrator from the activated WSL environment:

```bash
python -m scripts.bootstrap_admin
```

To allow self-registration for a local demonstration, explicitly set
`ALLOW_REGISTRATION=true` in `.env` and recreate the API. Registration always creates
an `ANALYST`; only an administrator can change roles.

Stop services while preserving named volumes:

```bash
docker compose stop
```

## Configuration

| Variable | Required | Description |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Host PostgreSQL URL using `postgresql+psycopg://` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Yes | Compose database initialization values |
| `POSTGRES_PORT` | No | Host database port; verified WSL value is `5433` |
| `API_PORT`, `REDIS_PORT` | No | Loopback host ports; defaults are `8000` and `6379` |
| `JWT_SECRET_KEY` | Yes | Private signing key containing at least 32 bytes |
| `ALLOW_REGISTRATION` | No | Enables local analyst registration; default `false` |
| `UPLOAD_DIRECTORY` | No | Local storage directory; Compose uses `/app/uploads` |
| `STORAGE_BACKEND` | No | `local` by default or `s3` |
| `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` | For S3 | Private S3 destination; credentials use the standard AWS chain |
| `OPENAI_API_KEY`, `LLM_MODEL` | For live AI | Provider credential and explicit model ID |
| `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS` | No | Embedding configuration; schema dimension is fixed at `1536` |
| `ANALYSIS_MAX_ATTEMPTS`, `ANALYSIS_RETRY_SECONDS` | No | Bounded worker retry policy |

All values and safe defaults are documented in [.env.example](.env.example).
Environment variables override the file. Compose changes database and Redis hosts to
their service names in memory; keep the WSL `DATABASE_URL` host as `localhost`.

## Main routes

| Route | Purpose |
| --- | --- |
| `GET /health/live`, `GET /health/ready` | Liveness and dependency readiness |
| `POST/GET /api/v1/auth/*` | Registration, login, refresh rotation, logout, and current user |
| `POST/GET /api/v1/incidents` | Create and list authorized incidents |
| `GET /api/v1/incidents/{id}` | Incident details and processing result |
| `POST /api/v1/incidents/{id}/analysis` | Start explicit reanalysis |
| `GET /api/v1/incidents/{id}/jobs/latest` | Persisted job progress and safe failure state |
| `GET/POST/DELETE /api/v1/incidents/{id}/files` | Authorized attachment lifecycle |
| `GET /api/v1/incidents/{id}/events` | Filtered redacted events |
| `GET /api/v1/incidents/{id}/similar` | Owner-scoped similar incidents |
| `PATCH /api/v1/incidents/{id}/resolution` | Human-confirmed cause and resolution |
| `GET /api/v1/incidents/{id}/report.pdf` | Authenticated RCA PDF |
| `POST/GET /api/v1/runbooks` | Upload, index, list, and manage runbooks |
| `POST /api/v1/runbooks/ask` | Retrieved, citation-validated runbook answer |
| `/api/v1/admin/*` | Administrator user and audit operations |

Swagger at `/docs` contains the complete request and response schemas.

## Verification

```bash
python -m ruff format --check app tests scripts
python -m ruff check app tests scripts
python -m pytest -v --cov=app --cov-report=term-missing
python -m scripts.verify_migrations
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
docker build --check .
```

The current checkpoint reports **220 passing tests** and **92.4% application coverage**.
Tests use synthetic data, temporary storage, SQLite isolation where appropriate, mocked
provider responses, and blocked live-provider calls. PostgreSQL migration verification
uses disposable schemas and rolls them back. GitHub Actions repeats formatting, linting,
migration verification, coverage, and the Dockerfile check with disposable PostgreSQL/
pgvector and Redis services.

Run the deterministic AI evaluation without a provider call:

```bash
python -m scripts.evaluate_ai
```

The three synthetic cases currently score `1.0` for parser, fields, redaction,
statistics, evidence, incident type, and information gaps, with `0.0` unsupported
claims. These fixtures verify the harness; they do not measure live-model quality.

## Demo data

Seed two resolved synthetic incidents for an existing account:

```bash
python -m scripts.seed_demo --email YOUR_ACCOUNT_EMAIL
```

The command is idempotent and does not request or print a password. Use the
[screenshot checklist](docs/screenshots/README.md) before publishing UI captures.

## Security and AI boundaries

- Uploaded files are private and accessed through authorized routes; internal storage
  keys are excluded from API responses.
- Known secret patterns are redacted before model analysis, but redaction cannot
  guarantee detection of every sensitive value.
- The browser stores bearer tokens in session storage and does not automatically rotate
  refresh tokens.
- External provider requests may repeat after a worker crash. Automated remediation is
  intentionally excluded.
- The production files are a single-host reference. Public deployment still requires
  HTTPS, private database and Redis networking, IAM, backups, monitoring, retention
  rules, and managed secrets.

See [SECURITY.md](SECURITY.md) for reporting and operational responsibilities.

## Deployment

The application includes a multi-stage image running as UID/GID `10001`, read-only API
and worker filesystems, dropped Linux capabilities, health checks, and a production
Compose override with Nginx. Local storage remains the default. For EC2, the S3 backend
can use an instance IAM role through Boto3's credential chain, avoiding static AWS keys
in the repository.

The project does not automatically create cloud resources. Follow the
[deployment and rollback guide](docs/deployment.md) before exposing it outside a local
machine.

## Project layout

```text
app/                  FastAPI app, models, routes, services, templates, and worker
scripts/              migrations, verification tools, evaluation, and demo seeding
scripts/migrations/   Alembic environment and five schema revisions
tests/                API, service, migration, queue, retrieval, UI, and release tests
evaluations/          synthetic offline AI evaluation cases
deploy/               Nginx reverse-proxy configuration
docs/                 architecture, deployment, milestone, and interview guides
.github/workflows/    continuous-integration workflow
```

## Documentation

- [Architecture](docs/architecture.md)
- [Deployment, backup, and rollback](docs/deployment.md)
- [Security policy](SECURITY.md)
- [Interview guide](docs/interview-guide.md)
- [Phase 4: retrieval and feedback](docs/phase-4.md)
- [Phase 5: browser UI and reports](docs/phase-5.md)
- [Phase 6: release readiness](docs/phase-6.md)
- [Earlier milestone history](docs/milestone-history.md)

## Limitations and roadmap

This is a single-host learning and portfolio application. It does not yet provide
organization-level tenancy, automatic retention, refresh-token rotation in the browser,
autoscaling, managed database/Redis failover, centralized monitoring, automatic disaster
recovery, or production-grade live-model evaluation. Logical next steps are organization
workspaces, automated retention, browser token renewal, OpenTelemetry export, managed
cloud data services, and a larger reviewed evaluation dataset.

## License

No license file is currently included. Add an explicit license before inviting external
reuse or contributions.
