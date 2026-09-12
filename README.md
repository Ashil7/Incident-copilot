# AI Incident & Log Analysis Copilot

Current checkpoint: **Phase 1, Milestone 1.5 - statistics and evidence: verified**.

Verified in WSL: Ruff formatting and lint passed; Pytest reported **80 passed,
2 dependency warnings**. The synthetic preview confirmed 6 errors, 1 warning,
HTTP error rate 0.625, average latency 1220.25 ms, p50 612.5 ms, and seven redacted
evidence items (E1-E7). Duration tokens normalize to `<duration>` in signatures
while measured latencies remain unchanged. Small decimal tails in interpolated
percentiles are floating-point representation, not additional measurement precision.
Milestone 1.6 has not started.

Milestone 1.5 adds `app/services/error_signatures.py`, `statistics.py`,
`evidence_selector.py`, their tests, and `scripts/preview_statistics.py`.
Settings now support `MAX_EVIDENCE_ITEMS` (default 30, range 1-100); `.env` is
not modified. No new dependencies, API routes, table changes, LLM calls, or jobs
are introduced. Statistics/evidence persistence and upload pipeline integration
remain Milestone 1.6 work.

### Deterministic calculation rules

- Each ERROR/CRITICAL/FATAL or HTTP status >=400 event counts once as an error.
  Warnings count independently by WARN/WARNING level.
- HTTP error rate is HTTP-error observations divided by observations with a known
  HTTP status. It is null without a denominator. Repeated log lines may describe
  the same request, so this is not claimed to be a unique-request error rate.
- Top five endpoints/services count error events only, with alphabetical tie breaks.
  Endpoint query strings remain redacted but are not otherwise canonicalized.
- Latencies include finite nonnegative observations. Empty summaries are null;
  min, max, average, p50, p90, p95, and p99 are calculated in Python.
- Percentiles use linear interpolation: sort values, calculate index
  `(n - 1) * p / 100`, and interpolate between its neighboring values. For
  `[0, 10, 20, 30]`, p95 is 28.5. A single-value percentile is that value.
- Error signatures normalize timestamps, UUIDs, duration tokens, and variable numbers in redacted
  messages. Level and HTTP status remain explicit grouping keys. Similar signatures
  are a heuristic, not proof of a shared cause. Enrichment returns event copies.
- Time summaries use offset-aware timestamps converted to UTC. Naive or missing
  timestamps are excluded and counted, never assigned an invented offset. Error
  buckets use one-minute intervals. The compact timeline marks first/last timed
  errors and the peak minute; it does not invent an incident end or recovery time.
- Redacted trace placeholders are counted, not treated as correlatable IDs. The
  current parser redacts trace IDs, so useful trace correlation is not available yet.

### Evidence rules and limits

Evidence candidates are errors, warnings, or observations with latency >=1000 ms.
Distinct signatures are prioritized by severity and then source line number.
Remaining capacity includes first/last error, highest latency, events next to the
initial failure, and the first successful HTTP observation after the last error.
That successful observation is explicitly not confirmed recovery. Each signature
can contribute its first, last, and slowest instances, plus adjacent context;
repeated messages do not fill the budget. Small budgets may omit context or later
signatures. Selection is deterministic, not a guarantee that every cause is represented.

Final evidence is ordered by source line and assigned E1, E2, etc. Each item contains
`evidence_id`, the normalized redacted `event`, and selection `reasons`. IDs are
stable for the same input/configuration, not across changed logs or limits. The
selector currently handles one source file and rejects duplicate line numbers.
It expects already-redacted parser output and performs no persistence or network I/O.

After formatting, linting, and tests, preview with:

```bash
python -m scripts.preview_statistics tests/fixtures/synthetic_logs.txt
```

Expected fixture checks: 14 lines, 13 events, 6 errors, 1 warning, 8 HTTP observations,
HTTP error rate 0.625, average latency 1220.25 ms, p50 612.5 ms, and maximum 5000 ms.
The preview prints statistics and capped redacted evidence, not raw input or settings.
Use `--max-evidence 5` to override the configured cap for a preview.

No new FastAPI concepts are introduced: these are ordinary Python calculations
and Pydantic output models. A Counter tallies repeated values, sorting fixes tie
order, and interpolation estimates a percentile between two observed values.
Tests remain offline. Verification is complete; run one guided command at a time.

Suggested commit: `feat: add deterministic incident statistics and evidence selection`.

Milestone 1.5 interview questions:

1. Why calculate statistics without an LLM? Python calculations are repeatable and testable.
2. Why null for an unknown error rate? Zero would wrongly imply measured absence of errors.
3. What does p95 mean here? A value at the 95% position under the documented interpolation rule.
4. Why diversify evidence? Repeated copies can hide distinct failures within a limited budget.
5. Why exclude naive timestamps from UTC buckets? Their offset is unknown, so mixing them
   would imply an ordering and absolute times the logs do not establish.

### Milestone 1.4 verification

Verified in WSL: Ruff formatting and lint passed; Pytest reported **60 passed,
2 dependency warnings**. The synthetic preview produced 14 total lines: 11 parsed,
0 partial, 1 blank, and 2 unparsed. Known fixture secrets were masked in messages
and extracted fields; seconds converted to milliseconds; original source line
numbers and missing values were preserved. The instruction-like line remained
ordinary log text. Milestone 1.5 implementation is described above.

Milestone 1.4 adds standalone `app/services/redactor.py` and `log_parser.py`,
`tests/test_redactor.py`, `tests/test_parser.py`, a synthetic fixture at
`tests/fixtures/synthetic_logs.txt`, and `scripts/preview_logs.py`. No new dependencies,
database tables, upload behavior, or API routes are introduced. Uploaded incidents
still remain UPLOADED; pipeline integration comes in Milestone 1.6.

### Redaction and parser contract

The parser redacts messages and extracted text fields before returning normalized
events. JSON objects are decoded in memory, recursively redacted, and only then
used to build events; raw decoded JSON is never returned or persisted. Text input
is redacted before field extraction. The functions make no database or provider calls.

Masking covers bearer/basic credentials; password, token, API key, secret, session,
cookie, trace/correlation ID assignments; email addresses; 12-19 digit account-like
numbers; common North American phone-like formats with optional country prefixes;
and sensitive query-string assignments. JSON secret values are masked regardless
of value type. IPv4 masking is optional via `mask_ipv4=True` or the preview flag.
Regex rules are deliberately conservative: cookie masking can discard the rest of
a text line. Unknown secret keys, unusual encodings, international phone formats,
and malformed/obfuscated input can evade redaction. This is not a privacy guarantee.
Existing raw synthetic upload files are not rewritten by these standalone services.

Each event contains line_number, timestamp, level, service, method, endpoint,
status_code, latency_ms, redacted trace_id, message, error_signature, and parse_status.
Missing/invalid fields are null. The parser leaves error signatures null;
Milestone 1.5 enriches copies of error events with normalized signatures.
Plain text supports ISO timestamps, common levels, METHOD /path followed by status,
explicit status/status_code assignments, and durations in ms or seconds. Timestamp
offsets are preserved; absent offsets stay absent. WARN normalizes to WARNING and
FATAL to CRITICAL. JSON aliases include time/timestamp, severity/level, path/endpoint,
http_method/method, status/status_code, duration_ms/latency_ms, and msg/message.
JSON durations are interpreted only in explicitly millisecond-named fields.

Line accounting is explicit: parsed means a timestamp and level were recognized;
partial means some fields were recognized without both; unparsed means none were
recognized (including malformed JSON); whitespace-only lines count as blank and
do not create events. Original 1-based line numbers are preserved, including gaps.
These counts describe parsing quality, not incident statistics. JSON-looking broken
lines stay unparsed instead of being reinterpreted as plain text. A tuple of parser
functions is the registry: each returns an event or None to try the next parser.
Custom parsers must preserve the same redaction and validation contract.

Pydantic models define the normalized output, like DRF serializers. Regular
expressions recognize supported patterns, not arbitrary language. The incremental
input loop reads lines, but the returned event list is kept in memory; this is a
learning-stage parser, not a large-file streaming analysis pipeline. No new FastAPI
concepts are required in this milestone: these services are ordinary Python functions.

Verification is complete for this milestone. In the guided session, run one requested command and
share its output before continuing. Existing Ruff and Pytest commands below include
the new modules. After tests pass, preview the synthetic fixture:

```bash
python -m scripts.preview_logs tests/fixtures/synthetic_logs.txt --redact-ipv4
```

Expected: normalized JSON with redacted messages, preserved source line numbers,
and parsing-quality counts. The injection-style message remains plain text; nothing
in log contents is executed or treated as instructions. Do not preview real private logs.

Suggested commit: `feat: add standalone log redaction and parsing with synthetic tests`.

Milestone 1.4 interview questions:

1. Why redact extracted fields too? An endpoint or service field can contain the same
   sensitive data as a message; masking only the message is insufficient.
2. Why null for missing fields? Invented values make later statistics misleading.
3. Why preserve line numbers? They let a human trace an observation to source evidence.
4. Why handle malformed lines independently? One broken record should not discard
   the rest of an otherwise useful log file.
5. Why use a parser registry? Additional explicit formats can be added without
   changing the input loop or normalized event contract.

### Milestone 1.3 verification

Verified in WSL on Python 3.12.3: Ruff formatting and lint passed; Pytest reported
**33 passed, 2 dependency deprecation warnings**. Live checks against PostgreSQL
confirmed upload creation (201), detail retrieval (200) with the same UTC timestamp,
listing (200), and unsupported-extension rejection (422). Internal paths were
absent from the create/detail responses. Empty files, size boundaries, invalid
metadata/text, rollback cleanup, pagination, and missing IDs were covered by the
automated suite. Milestone 1.4 implementation is described above.

Milestone 1.3 adds `app/routers/incidents.py`, `app/services/uploads.py`, and
`tests/test_incidents.py`. The existing table and response schema are reused.
Install the updated dependencies before restarting Uvicorn:

```bash
python -m pip install -r requirements-dev.txt
```

New endpoints:

| Endpoint | Behavior |
| --- | --- |
| `POST /api/v1/incidents` | Multipart upload and incident metadata; returns 201, status UPLOADED |
| `GET /api/v1/incidents` | Newest first; limit defaults to 20, maximum 100; offset defaults to 0 |
| `GET /api/v1/incidents/{incident_id}` | Detail, 404 for an unknown UUID, 422 for malformed UUID |

POST fields: required `title` (1-200 characters, not whitespace-only), optional
`service_name` (maximum 200), `environment` (DEV/UAT/PROD; default DEV), and required
`log_file`. Supported files are .log/.txt with text/plain or application/octet-stream
MIME type. Bytes must be valid UTF-8 without NUL bytes; the MIME header alone is
not trusted. Empty files return 422 and files exceeding MAX_UPLOAD_SIZE_MB return 413.
One MB means 1,048,576 bytes. Relative UPLOAD_DIRECTORY paths resolve from the project
root. Filenames are generated UUIDs; original filenames are display-only metadata.
Internal storage paths are omitted from create, list, and detail responses.
Application-created timestamps are serialized consistently in UTC. The response
schema restores UTC metadata when the SQLite test database returns naive timestamps;
timezone-aware database values are converted to UTC.

FastAPI **Form** reads multipart text fields, like form fields in Django requests.
**UploadFile** gives a spooled temporary file rather than a single bytes value.
The synchronous handler copies it in 64 KiB chunks, closes it in finally, and removes
partial files on validation/write failure. Database failures trigger rollback and
saved-file cleanup. **Query** validates pagination and the typed UUID path parameter
validates incident IDs. **201 Created** means a row and file were saved; analysis is
not scheduled yet, so this endpoint does not claim 202 Accepted/background processing.

Manual verification, after dependency installation and startup: open `/docs`, create
an incident using a small synthetic .log/.txt file, then use the returned ID in GET
detail. List should contain it. Invalid extension/empty upload should return 422.
The guided session supplies one command at a time; wait for each result before continuing.

Limitations: the framework parses/spools multipart data before the handler runs;
this file-copy limit is not a total HTTP request-body or temporary-disk quota.
Authentication, malware scanning, redaction, parsing, analysis, and crash recovery
are not implemented yet. Raw synthetic uploads are stored locally and are not served
as static files. A process crash between file storage and database commit can leave
an orphan file; filesystem and database writes are not one atomic transaction.
Use synthetic data only. Do not expose this unauthenticated learning API publicly.

Suggested Milestone 1.3 commit: `feat: add secure log upload and incident retrieval APIs`.

Milestone 1.3 interview questions:

1. Why multipart? It carries file bytes and ordinary form fields together.
2. Why generated filenames? User-provided paths never control where files are stored.
3. Why chunked copying? It bounds application copy-buffer memory and counts actual bytes.
4. Why rollback and unlink? They clean up the two storage systems when creation fails.
5. Why bounded pagination? It prevents a list request from returning every stored incident.

Reference: [FastAPI forms and files](https://fastapi.tiangolo.com/tutorial/request-forms-and-files/).

## Previous checkpoint verification
Milestone 1.1 was verified by the user. Milestone 1.2 offline checks passed in WSL
on Python 3.12.3: Ruff formatting and lint passed; Pytest reported **20 passed,
2 dependency deprecation warnings**. The user also verified real PostgreSQL through
localhost:5433: `/health/ready` returned HTTP 200 with `{"status":"ok"}`, and
`scripts.verify_database` passed connectivity, table presence, UUIDs, defaults,
timezone handling, JSON storage, response privacy, and rollback. Milestone 1.2 is
complete. Milestone 1.3 verification results are recorded above.

This application will help investigate synthetic application logs. Python extracts,
redacts, validates, and measures facts; the LLM will explain evidence and suggest
investigation steps. A human confirms root causes and resolutions.

## Implemented scope

- FastAPI application, typed settings, Swagger and OpenAPI.
- GET `/health`: application liveness, returning `{"status":"ok"}`.
- GET `/health/ready`: executes `SELECT 1`; returns 200 when available, or 503
  with `{"detail":"Database unavailable."}` after a database failure.
- Synchronous SQLAlchemy 2.x engine, session factory, Base, and `get_db` dependency.
- Initial Incident ORM model and public response schema excluding internal paths.
- Learning-stage table creation during application startup.
- Ruff formatting/linting and offline Pytest checks.

Upload/create/list/detail routes are implemented and verified in Milestone 1.3.
Authentication, migrations, workers, RAG, dashboard, and deployment remain planned.

## Repository responsibilities

| File | Responsibility |
| --- | --- |
| `app/main.py` | App assembly, model registration, startup and shutdown |
| `app/config.py` | Typed configuration from environment and optional .env |
| `app/database.py` | Declarative Base, engine, sessionmaker, request dependency |
| `app/models.py` | Initial Incident model and environment/status enums |
| `app/schemas.py` | Public incident response schema |
| `app/routers/health.py` | Liveness and database readiness |
| `app/legacy_main.py` | Compatibility import of the main app; no duplicate startup |
| `docker-compose.yml` | PostgreSQL service, health check, persistent volume |
| `tests/` | Settings, API, lifecycle, transaction, and readiness checks |
| `scripts/verify_database.py` | Opt-in real PostgreSQL round-trip check |
| `pyproject.toml` | Ruff, Pytest, coverage configuration |

The earlier database implementation was reused without changing its table layout.
`app.main` explicitly imports models with a documented `noqa: F401` because the
import registers tables in `Base.metadata`. Removing it can leave metadata empty.
The old `app.legacy_main:app` command resolves to the same current app.

## WSL setup

Use Python 3.12 with `.venv-wsl` activated. The verified WSL interpreter is Python
3.12.3. Run FastAPI directly in WSL and PostgreSQL through Docker Compose.
For a fresh environment, run `python3.12 -m venv .venv-wsl`, then
`source .venv-wsl/bin/activate`. Do not reuse a Windows virtual environment in WSL.

Install dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Preserve your existing `.env` credentials. A fresh clone can copy `.env.example`
to `.env` and fill in its own credentials. This milestone does not overwrite `.env`.

| Variable | Configuration |
| --- | --- |
| `APP_NAME` | Defaults to AI Incident Copilot |
| `APP_ENV` | development, test, or production; currently a label |
| `DEBUG` | Defaults to false; keep false outside local development |
| `DATABASE_URL` | Required at startup; postgresql+psycopg URL using localhost:5433 |
| `POSTGRES_PORT` | 5433 on the Windows/WSL host |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Your existing Compose credentials |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | Unused in this milestone |
| `UPLOAD_DIRECTORY`, `MAX_UPLOAD_SIZE_MB` | Reserved upload settings |

URL shape (placeholders only):
`postgresql+psycopg://YOUR_USER:YOUR_URL_ENCODED_PASSWORD@localhost:5433/YOUR_DATABASE`.
The container still listens on **5432**. Compose publishes
`127.0.0.1:${POSTGRES_PORT:-5433}:5432`. An explicit `POSTGRES_PORT` in `.env`
overrides this default; keep it consistent with DATABASE_URL. A future API running
inside Compose would connect to `db:5432`, not localhost.

Settings load the project-root `.env`; environment variables override file values.
Secrets use masked representations, not encryption. Never share or commit `.env`.

In the guided session, run one requested command and share its output before the next.
The following commands are a reference, not a request to run them all at once.

Start PostgreSQL:

```bash
docker compose up -d --wait db
```

Expect `db` to become healthy. Start FastAPI:

```bash
python -m uvicorn app.main:app --reload
```

Expect `Application startup complete` on port 8000. Startup now requires a usable
PostgreSQL connection. Missing configuration or database failures stop startup.
No connection or table creation occurs merely by importing app.main.

In another WSL terminal:

```bash
curl -i http://127.0.0.1:8000/health/ready
```

Expect HTTP 200 and `{"status":"ok"}`. `/health` retains the same successful
response from Milestone 1.1. Open http://localhost:8000/docs to try both routes.
Swagger is an interactive client generated from `/openapi.json`; its browser
assets need CDN access.

With the API started and the WSL environment active, verify real PostgreSQL:

```bash
python -m scripts.verify_database
```

Expect PASS for connectivity, table presence, UUID, defaults, timezone-aware
PostgreSQL timestamps, JSON, response privacy, and rollback. It inserts a synthetic
row inside a transaction and rolls back, leaving no test row. Run this explicitly;
it is not part of the offline default tests. Restarting the API creates only missing
tables and preserves existing data.

## Tests and quality checks

```bash
python -m ruff format app tests scripts
```

```bash
python -m ruff check app tests scripts
```

```bash
python -m pytest -v
```

Optional coverage: `python -m pytest --cov --cov-report=term-missing`.
The default suite uses isolated in-memory SQLite and mocked failures, never your
.env or PostgreSQL credentials. It checks startup, table registration, commit,
refresh, rollback, session cleanup, readiness, response privacy, and existing
foundation behavior. SQLite tests do not prove PostgreSQL enum, timezone, or
connection behavior; the explicit PostgreSQL verification fills that gap.

## Concepts explained

- **Engine:** SQLAlchemy's connection manager and pool. Reuse one for the app;
  do not create a new pool for every request. Psycopg is its PostgreSQL driver.
- **sessionmaker:** a configured factory that creates individual sessions.
- **Session:** tracks ORM objects and changes within a transaction. It is not a
  global shared database connection and must not be shared across requests.
- **Base:** the parent for ORM models; collects the table definitions in metadata.
- **ORM model:** a Python class mapped to a database table, similar to a Django
  model. Incident retains UUID strings, environment/status enums, JSON results,
  optional file metadata, and UTC timestamps. File paths are private.
- **get_db dependency:** FastAPI calls it for `Depends(get_db)`, supplies the yielded
  session to the route, and closes the session after success or failure. Closing
  releases resources and rolls back uncommitted work. It does not auto-commit.
- **commit():** flushes pending SQL and makes the transaction durable. Unlike the
  common Django autocommit workflow, changes here need an explicit commit.
- **refresh():** reads a row again into an ORM object, useful for values/defaults
  stored by the database. `flush()` sends SQL without making the transaction durable.
- **rollback():** discards uncommitted transaction changes and makes a session usable
  again after a failed transaction; it cannot undo an already committed transaction.
- **Lifespan:** code before `yield` prepares the app; code after it releases resources.
  Startup uses `Base.metadata.create_all`; shutdown disposes the engine, even after
  a startup failure. Synchronous startup work happens before serving requests.
- **Synchronous route:** FastAPI runs a normal `def` handler in a thread pool, suitable
  for synchronous ORM calls. Readiness therefore uses `def`, not blocking SQL in an
  `async def` handler.
- **Pydantic schema:** describes the public API data, like a DRF serializer; it is
  separate from the database table model.

```mermaid
flowchart LR
    WSL[FastAPI in WSL] --> Engine[SQLAlchemy pool]
    Engine --> Host[localhost:5433]
    Host --> DB[PostgreSQL container:5432]
    Startup[App startup] --> Tables[Create missing registered tables]
    Tables --> DB
```

## Limitations and checkpoint

`create_all` creates missing tables, not migrations. It does not alter existing
columns, enums, or constraints; schema changes need Alembic in a later phase.
PostgreSQL initialization credentials only apply to an empty volume; changing
.env does not change an existing database password. Named volumes persist data.
During local verification, the stored role password needed to be synchronized with
the existing configured password using psql's interactive `\password` command.
No `.env` credentials or database volume were replaced. Container loopback rules
used `trust`, so a successful loopback `SELECT 1` did not validate the password;
connections from WSL required SCRAM authentication. A healthy container alone is
therefore not proof that the application's database credentials work. Do not
weaken authentication rules to resolve a password mismatch.
`docker compose stop db` retains data. Do not remove volumes to fix credentials.

Readiness checks current database connectivity; it is not a migration audit. Liveness
can remain 200 after a running database becomes unavailable, but initial startup
requires the database. No production readiness, authentication, or upload behavior
is claimed. Dependency deprecation warnings from Starlette/AnyIO were seen in the
previous checkpoint and are not suppressed.

Suggested commit: `feat: integrate milestone 1.2 database lifecycle and readiness`

Interview questions:

1. Why share an engine but not a session? The pool is reusable; session transaction
   state belongs to one unit of work/request.
2. Why import models before create_all? Imports register their table definitions
   in Base.metadata, which create_all reads.
3. What is commit versus flush? Flush sends SQL within a transaction; commit makes
   it durable. Rollback can still undo a flush.
4. How does get_db clean up after an exception? The generator resumes/unwinds its
   context manager, closing the session and releasing its connection.
5. Why localhost:5433 rather than db:5432? The API is on the WSL host; it uses the
   published host port. db:5432 is the Compose-network address.

References: [SQLAlchemy sessions](https://docs.sqlalchemy.org/en/20/orm/session_basics.html)
and [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/).
