# Milestone 2.1: migrations and normalized schema

Verified on 2026-09-12 in WSL Python 3.12.3: Ruff passed and 102 tests passed with
97% coverage and two dependency deprecation warnings. Local Windows tests also passed.
The user created a backup and verified its archive listing (a full restore was not
tested), confirmed the legacy schema, passed the disposable PostgreSQL migration
tests, and upgraded the application database to `0002_normalized`.

Database verification passed; the rebuilt API and PostgreSQL containers are healthy.
Readiness returned 200 on port 8001. The existing Milestone 1.7 incident retained its
statistics and analysis. A fresh incident, `13ec645d-395c-41e7-8c08-d6f8883fc393`,
returned 202 and then 200 with COMPLETED status and deterministic analysis.
`.env` is unchanged. Live provider success remains unverified. Milestone 2.1 is complete;
Milestone 2.2 has not started.

## Implementation and compatibility

`app/models.py` became a package containing incident, user, processing, and governance
models plus shared mixins. Package exports preserve existing imports.
`app/legacy_main.py` remains a compatibility entry point. `app/database.py` still
provides the synchronous engine, Base, and session dependency.

| Table | Purpose |
| --- | --- |
| users | Normalized unique email, password hash, role, activity, timestamps |
| refresh_tokens | Hashed token identifiers, user references, expiry and revocation |
| incidents | Existing fields plus nullable ownership, description, severity, human resolution fields, incident times, updated timestamp |
| log_files | Storage keys, original names, MIME types, sizes and checksums |
| log_events | Structured redacted events, indexed fields, file/line identity |
| analysis_jobs | Future worker status, progress, attempts and safe errors |
| incident_analyses | Structured results and provider usage metadata |
| feedback | User feedback and optional 1–5 rating |
| audit_events | Actions and safe metadata |

No accounts or ownership are invented for legacy records. UUIDs remain UUID strings
in VARCHAR(36), preserving existing IDs. The PostgreSQL environment/status enum
types remain unchanged. Foreign keys restrict deleting referenced records.

The new tables are schema groundwork, not new APIs. Original file metadata,
statistics, and analysis JSON remain on incidents as the active pipeline's source
of truth. They are not copied into incomplete normalized records. Storage and worker
milestones will adopt the new tables and explicitly backfill before removing old
columns. No raw events are backfilled. Runbook/vector tables wait for Phase 4.

## Concepts

A **migration** is a recorded database change, like a Django migration. An Alembic
**revision** contains upgrade and downgrade operations. The **head** is the latest
revision; `alembic_version` records the database's current version. An **upgrade**
executes changes; **stamp** only records a version. The helper stamps a legacy
database only after checking its Phase 1 schema and PostgreSQL enum labels.

**Normalization** gives related entities separate tables. A **foreign key** requires
a reference to an existing row. A **unique constraint** prevents duplicates; a
**check constraint** limits valid values. An **index** speeds lookups with storage
and write overhead. A **mixin** shares ORM columns such as IDs and timestamps.
Python timestamp defaults run during ORM writes; raw SQL callers must provide
required values. These defaults are not database triggers.

Revision `0001_phase1` freezes the original schema. Revision `0002_normalized`
adds the new tables/columns and fills legacy `updated_at` from `created_at`.
Revision files do not import evolving application models. Upgrade drops no original
incident columns. Startup checks the revision instead of changing tables. PostgreSQL
DDL and adoption run in one transaction, with an advisory lock between cooperating
migration commands. Stop API writers before migration.

## Verification in WSL

Run one command at a time and stop on errors. Use `.venv-wsl` in the project directory.

1. Install dependencies:

   ```bash
   python -m pip install -r requirements-dev.txt
   ```

2. Run these checks separately:

   ```bash
   python -m ruff format app tests scripts
   python -m ruff check app tests scripts
   python -m pytest -v --cov=app --cov-report=term-missing
   ```

   API fixtures now run real Alembic revisions on disposable SQLite databases.
   Migration tests cover fresh setup, legacy data preservation, schema/model
   agreement, repeated upgrade, schema mismatch rejection, disposable downgrade
   and re-upgrade, normalized email uniqueness, foreign keys, and startup rejection
   of an unmigrated database. SQLite does not replace PostgreSQL verification.

3. Ensure `db` is healthy. Stop WSL Uvicorn with Ctrl+C, or stop the Compose API:

   ```bash
   docker compose stop api
   ```

4. Create a backup directory, then a private PostgreSQL custom-format backup:

   ```bash
   mkdir -p backups
   docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/before-milestone-2.1.dump
   ```

   Use a different filename if this backup already exists. `backups/` is excluded
   from Git and Docker builds. Keep the backup private; it contains database data.

5. Inspect the existing schema without changing it:

   ```bash
   python -m scripts.migrate check
   ```

   Expect `legacy`, `empty`, or a known revision. Unexpected tables, column
   differences, and enum differences prevent adoption. Do not bypass a rejection
   using `stamp head`.

6. Verify PostgreSQL-specific migrations in disposable schemas:

   ```bash
   python -m scripts.verify_migrations
   ```

   Expect PASS. This requires permission to create schemas. The script uses random
   schema names and a transaction-local search path, tests fresh and legacy upgrade,
   preservation, model agreement, and downgrade/re-upgrade, then rolls everything
   back. It never downgrades the application schema.

7. Apply the migration:

   ```bash
   python -m scripts.migrate upgrade
   ```

   Expect `Database migration state: 0002_normalized`. WSL still uses
   `localhost:5433`; Compose uses `db:5432`. Repeating upgrade at head is a no-op.

8. Verify PostgreSQL ORM behavior, then rebuild/start the API:

   ```bash
   python -m scripts.verify_database
   API_PORT=8001 docker compose up --build -d --wait
   ```

9. Check readiness and the preserved Milestone 1.7 incident separately:

   ```bash
   curl -i http://127.0.0.1:8001/health/ready
   curl -i http://127.0.0.1:8001/api/v1/incidents/06ba1389-f300-4e31-b58e-cba80f1b239e
   ```

   Expect 200 and the original completed incident. Finish with a fresh synthetic
   healthy upload and poll its ID using the README example on port 8001.

Downgrades remove new tables and their data. Use them only on disposable test
databases, not as a routine rollback on your working database. Recovery should use
a tested backup. Autogenerate is a starting point; review future revisions carefully.

References: [Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
and [stamp semantics](https://alembic.sqlalchemy.org/en/latest/api/commands.html#alembic.command.stamp).
