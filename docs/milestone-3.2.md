# Milestone 3.2: durable jobs, progress, and recovery

Verified on 2026-09-13. The user reported 189 tests passed in WSL and verified the
backup archive `backups/before-milestone-3.2.dump`. PostgreSQL verification passed
fresh/legacy migrations, schema comparison, preservation, downgrade/re-upgrade,
worker-lock exclusion, and active-job uniqueness. The user upgraded the application
database to `0004_analysis_jobs`; database smoke checks passed.
All four rebuilt Docker services are healthy. Live verification passed persisted
job progress, completion, retry eligibility, and explicit reanalysis with a new job
ID. Synthetic incident `7739e97b-8b3f-4245-9a33-e0ebdca7548a` was retained.
The recovery command republished zero eligible jobs; this does not independently
prove that no future-dated retries exist. No `.env` credentials were changed.
Local Windows verification: Ruff formatting and linting passed; Pytest reported
189 passed with two existing dependency deprecation warnings. Controlled transient
failures, checkpoint recovery, and failed-job manual retry were verified offline
with mocks; the live smoke test used deterministic processing without an LLM call.

## What this milestone builds

Each upload, attachment, or deletion creates an `AnalysisJob` in the same transaction
as its incident/file changes. A committed job remains available even when publishing
to Redis fails. Messages now carry the job ID as well as the incident/request IDs.
The Celery task ID is the job ID. PostgreSQL holds progress and results; Redis is
only the transport. File deletion creates a cleanup-only job when no files remain.
Storage-deletion records remain independently retriable if storage is unavailable.

The existing pipeline is reused through `perform_analysis`. The earlier
`run_analysis` entry point delegates to durable jobs for compatibility with scripts
and tests; it no longer bypasses job state. Pre-migration queued messages without a
job ID are mapped to a durable job when their incident is still UPLOADED. Completed
old messages are ignored. Finish old running work before upgrading: this migration
does not invent jobs for historical interrupted incidents that have no queued message.

## Concepts

A **transaction** saves the job and uploaded-file metadata together. An **idempotent**
operation can safely be repeated: terminal jobs are ignored, incomplete deterministic
stages can be repeated, and statistics are reused once their checkpoint commits.
The validated final analysis and completed job state commit together.

A PostgreSQL **partial unique index** allows only one PENDING, RUNNING, or RETRY
job per incident. API mutation paths also lock the incident row when creating jobs.
A **session advisory lock** gives one worker exclusive execution for that incident
across stage commits. A terminated database connection releases the lock. Workers
check an attempt number before committing stages, so an older attempt cannot overwrite
a newer one after losing its execution lock. SQLite tests use a process lock;
the PostgreSQL verification separately checks real connection-level exclusion.

Progress is a persisted milestone percentage, not a time estimate:

| Stage | Progress |
| --- | --- |
| QUEUED | 0 |
| PARSING | 10 |
| CALCULATING | 25, then 40 after statistics/evidence commit |
| GENERATING_ANALYSIS | 60 |
| VALIDATING | 85 |
| COMPLETED / cleanup complete | 100 |

Progress never decreases within a job. A resumed job can revisit an earlier stage
while retaining its highest percentage. A manual retry creates a new job starting
at zero, preserving the previous job's outcome. File edits invalidate old analysis
and statistics and create a new job; old terminal deliveries cannot modify it.

## Retry policy and limits

`ANALYSIS_MAX_ATTEMPTS` defaults to 3 (range 1–10), including the first attempt.
`ANALYSIS_RETRY_SECONDS` defaults to 5 (range 1–60). Transient provider connection/
timeout failures, rate limits, provider HTTP 5xx, and SQLAlchemy OperationalError
receive bounded exponential backoff, capped at 300 seconds. With defaults the two
retry waits are 5 and 10 seconds. The OpenAI SDK's own automatic retries are disabled
so they do not multiply the job budget. Missing configuration, invalid data/schema,
and invalid evidence references fail without automatic retry. Error details and
credentials are never returned in job responses.

Celery acknowledges after execution and requeues work when a worker child is lost.
Soft/hard execution limits are 600/630 seconds. Interrupted attempts count toward
the database attempt limit. Separate infrastructure/lock retry scheduling is capped
at 10 Celery retries; if those exhaust, the durable job remains available for operator
recovery. Future-dated RETRY jobs do not consume another attempt before they are due.

Delivery is at least once, not exactly once. A provider call can repeat if a process
dies after the call but before the final transaction commits; repeated calls can incur
cost. Statistics/evidence checkpoints contain redacted data, not raw logs. There is
no durable checkpoint for an unvalidated provider response. A job attempt may restart
parsing if its statistics were not committed. No automatic recovery scheduler is
installed: run the recovery command after broker outages or stranded deliveries.
Redis still uses append-only persistence with `appendfsync everysec`.
After an entire worker host disappears, Redis redelivery can wait for Celery's
default visibility timeout (one hour). Operator recovery can republish the durable
job sooner; execution locks prevent an overlapping active worker from proceeding.

## Endpoints

| Endpoint | Behavior |
| --- | --- |
| GET /api/v1/incidents/{id}/jobs/latest | Latest job's stage, progress, attempts, times, and safe error |
| POST /api/v1/incidents/{id}/analysis | Explicit analysis of an editable incident with files; 202 |
| POST /api/v1/incidents/{id}/analysis/retry | New job for a failed incident/job; 202 |

Active jobs block duplicate requests and file edits with 409. A completed job is
not eligible for the failed-job retry endpoint; use explicit analysis instead.
Analysts can access only their incidents; administrators retain cross-owner access.
Cross-user and missing incidents return 404. Older incidents without any job return
404 from jobs/latest. Responses omit Celery identifiers and internal storage details.
Explicit analysis and retry requests are audited.

## Migration and verification: one command at a time

Run each command and wait for the result before continuing. Start with offline checks:

```bash
python -m ruff format app tests scripts
```

```bash
python -m ruff check app tests scripts
```

```bash
python -m pytest -v
```

After existing work finishes, stop API and worker writers (stop any direct WSL
Uvicorn/worker processes too):

```bash
docker compose stop api worker
```

Keep PostgreSQL available for backup:

```bash
docker compose up -d --wait db
```

```bash
mkdir -p backups
```

Create a new backup without overwriting an existing one:

```bash
(set -o noclobber; docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/before-milestone-3.2.dump)
```

Stop if the backup fails. A failed redirected command can leave an empty file; use
a new filename for a retry and carry that filename into the verification command.
Verify the archive can be listed (this is not a full restore test):

```bash
docker compose exec -T db pg_restore --list < backups/before-milestone-3.2.dump > /dev/null && printf 'Backup archive verified\n'
```

Check the current revision, expected `0003_storage_cleanup`:

```bash
python -m scripts.migrate check
```

Test fresh/legacy upgrades, preservation, schema comparison, active-job uniqueness,
and real PostgreSQL worker lock exclusion using disposable schemas rolled back afterward:

```bash
python -m scripts.verify_migrations
```

Only after those pass, apply the new revision:

```bash
python -m scripts.migrate upgrade
```

```bash
python -m scripts.migrate check
```

Expect `0004_analysis_jobs`. This adds timestamps, request correlation, operation
flags, and an active-job unique index. Existing records are preserved. If duplicate
active job rows already exist, the migration stops rather than deleting or rewriting
them. Startup still verifies schema only; it does not migrate automatically.

```bash
python -m scripts.verify_database
```

Rebuild the API and worker together:

```bash
API_PORT=8001 docker compose up --build -d --wait
```

Then run the synthetic live smoke test with existing credentials entered privately:

```bash
python -m scripts.verify_jobs
```

It checks job completion/progress, rejection of retry for a completed job, and explicit
reanalysis creating a new job. It retains one synthetic incident and uses no LLM call.
Transient failures, failed-job manual retry, checkpoint reuse, stale-attempt fencing,
and retry exhaustion are covered by mocked offline tests.

The recovery command republishes up to 100 unfinished, due jobs with their original
job IDs, request IDs, and operation flags. It never clears attempt limits or turns
completed/failed jobs back into active jobs:

```bash
docker compose exec worker python -m scripts.recover_jobs --container
```

Normally expect zero after the smoke test. Republished messages can duplicate messages
already in Redis; locks and terminal-state checks make these safe. Repeat after a
retry becomes due if it was not yet eligible. This is an operator tool; the HTTP retry
endpoint instead creates a new job after a terminal failure.

Stop after Milestone 3.2. Prompt/provider improvements belong to Milestone 3.3.

Reference: [Celery task acknowledgement and retries](https://docs.celeryq.dev/en/stable/userguide/configuration.html).
