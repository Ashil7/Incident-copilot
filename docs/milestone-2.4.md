# Milestone 2.4: multiple files and storage

Milestone 2.4 is verified. Local Windows Python 3.12.2 checks passed: Ruff and 153
tests, with two existing dependency deprecation warnings. The user also reported
checks passed and 153 tests passed in WSL; no new WSL coverage percentage was supplied.

The successful backup is `backups/before-milestone-2.4-retry.dump`; its archive
listing was verified, not a full restore. The original backup attempt failed while
PostgreSQL was stopped and must not be treated as a valid backup.
Disposable PostgreSQL migration tests passed and the user applied
`0003_storage_cleanup`. Both rebuilt Docker services are healthy on the existing
port 8001 setup.

Live verification passed multiple uploads, SHA-256, private metadata, combined
analysis, attachment, deletion, and empty state. The synthetic empty incident
`1d05bd8a-365a-4f05-913d-ae0d6a1bea63` remains. Cleanup processed zero additional
deletions; a separate database check confirmed zero pending deletions.
The assistant did not read or change `.env` credentials. Milestone 2.5 has not started.

## Storage and API behavior

The **storage interface** defines put, open, and delete operations. The **local
adapter** implements them on disk. Upload validation and normal file processing use
this contract; a future S3 adapter can implement the same operations. S3 is not added
here. Local path handling remains in the adapter and legacy compatibility code.

Uploads use generated UUID keys, exclusive file creation, UTF-8 validation, NUL
rejection, chunked size limits, and SHA-256 checksums. The original name is metadata
only. `.log`, `.txt`, and `.json` logs are accepted with text/plain,
application/octet-stream, or application/json MIME types. Content bytes are checked;
MIME headers alone are not trusted. JSON syntax remains the tolerant parser's job:
invalid records can become unparsed events. Markdown/PDF runbooks are not supported
by the log endpoint. Raw synthetic uploads remain on disk; parsed evidence is redacted.

A **checksum** detects changed bytes; it does not authenticate a sender or prove
the log is truthful. Processing verifies each file's size and SHA-256 before parsing.
File metadata responses include ID, incident ID, original name, MIME type, size,
checksum, and upload time. Keys, absolute paths, and storage-location identifiers
are excluded.

POST `/api/v1/incidents` keeps the original single `log_file` field and additionally
accepts repeated `log_files`. At least one file is required; the default cap is ten
per incident, controlled by MAX_FILES_PER_INCIDENT. Each file defaults to a 5 MB
limit. A failed file in a batch rolls back all new metadata and removes successfully
written objects from that batch. Framework multipart spooling precedes these limits;
this is not a global HTTP request quota.

GET `/api/v1/incidents/{id}/files` lists authorized metadata.
POST that path accepts repeated `log_files` and returns 202 with the newly added
metadata. DELETE `/{file_id}` returns 204. Ownership and administrator rules apply
to every file operation, including matching the file to the specified incident.

File changes lock the incident and are allowed only in CREATED, COMPLETED, or FAILED.
Queued/running processing returns 409. Successful attachment or deletion clears
stale statistics/analysis and schedules analysis of all remaining files. Deleting
the last file leaves the incident CREATED, with empty file metadata and no analysis.
File changes can therefore trigger another provider call for error-bearing logs.
Use the healthy synthetic verification script to avoid model calls.

Files are processed by upload timestamp then ID. Evidence retains a combined line
number plus source_file_id and source_line_number, keeping file-local provenance
without exposing filenames or storage keys. Statistics cover all files. Normalized
LogEvent/IncidentAnalysis persistence and durable workers remain later work.

## Legacy records and storage locations

Old incident fields are retained. A legacy record's file list is empty until its
original upload is adopted. Attaching another file adopts the old upload within the
same transaction, without copying or deleting it, only if it is available under the
current upload root. Missing/foreign-environment legacy files cause 409 and preserve
the incident. There is no bulk backfill and no filesystem access during migration.

New file metadata includes an internal storage-location identifier derived from
the resolved upload root. WSL and Docker uploads are separate storage locations;
an API cannot edit/process a file set belonging to the other location. Do not switch
upload roots expecting files to move automatically. A future storage migration must
copy/verify objects and update metadata explicitly.

## Cleanup and migration

Migration `0003_storage_cleanup` adds nullable log_files.storage_scope and the
storage_deletions table. It preserves all previous schema/data. Existing normalized
file rows without a location identifier are not assumed to belong to local storage.

Database commits and filesystem deletion cannot form one atomic transaction. A
**pending-deletion queue** records the object key/location in the same transaction
that removes file metadata. After commit, the background task deletes the object
and removes the queue row. Missing objects count as already deleted. Failures leave
the row for retry, and an object still referenced by file metadata is not removed.
The queue is internal and never exposed through the API.

Retry pending deletions in the same environment that owns the files. For Compose:

```bash
docker compose exec api python -m scripts.cleanup_storage --container
```

For WSL-owned files, use `python -m scripts.cleanup_storage` in WSL. Each run handles
up to 100 matching queue entries. Other storage locations are left alone. A failed
unlink of an uncommitted upload or a crash before its database commit can still
leave an orphan; this implementation logs a safe message and does not automatically
scan/delete untracked objects. Startup does not sweep upload directories.

## Verification: one command at a time

No new dependency is required. In `.venv-wsl`, run these separately:

```bash
python -m ruff format app tests scripts
python -m ruff check app tests scripts
python -m pytest -v --cov=app --cov-report=term-missing
```

Tests cover whole-batch rollback, existing behavior, multi-file statistics/provenance,
SHA-256 tampering, file limits, permissions, active-state conflicts, legacy adoption,
database deletion failure, storage retry, and storage-location isolation.

Stop API writers before migration:

```bash
docker compose stop api
```

Create a fresh backup (backups directory from Milestone 2.1 already exists):

```bash
(set -o noclobber; docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > backups/before-milestone-2.4.dump)
```

Validate its archive listing, then run preflight, disposable PostgreSQL migration
tests, and upgrade separately:

```bash
docker compose exec -T db pg_restore --list < backups/before-milestone-2.4.dump > /dev/null
python -m scripts.migrate check
python -m scripts.verify_migrations
python -m scripts.migrate upgrade
```

Expect the old revision before upgrade and `0003_storage_cleanup` afterward.
Rebuild/start using host port 8001:

```bash
API_PORT=8001 docker compose up --build -d --wait
```

Run the new file smoke test from WSL:

```bash
python -m scripts.verify_files
```

Enter an existing active account's credentials privately. It verifies two-file
creation, metadata checksums, combined processing, attachment of a third file,
deletion/reanalysis, and final empty state. It leaves an empty synthetic incident
and audit events; credentials stay in memory. It logs out its refresh token afterward.
Use the cleanup command afterward to retry any pending Docker object deletions.

Stop after Milestone 2.4. Milestone 2.5 handles consistent domain errors, request IDs,
structured logging, and further readiness work.
