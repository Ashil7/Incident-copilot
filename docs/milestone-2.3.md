# Milestone 2.3: ownership, permissions, filters, and audit events

Verified on 2026-09-12. WSL Python 3.12.3 reported 136 tests passed, 96% coverage,
and two dependency deprecation warnings. The subsequent bootstrap diagnostic fix
added three tests; Ruff and 15 targeted tests passed locally. A full WSL suite was
not rerun after that diagnostic-only change.

Both rebuilt Docker services are healthy. The user created the first administrator
and passed the live permissions smoke test: authenticated upload, owner access,
cross-user 404/list isolation, anonymous 401, analyst admin denial, processing,
administrator cross-owner access, user listing, and creation audit. The successful
run retained two synthetic analysts and incident `9ae1aa02-c404-4717-8525-d2bbc4807afa`.
Earlier attempted smoke runs may also have retained test records.
No schema revision or dependency change was needed; `.env` was not changed by the
assistant. Milestone 2.3 is complete; Milestone 2.4 has not started.

## Access rules

All existing incident routes require an active authenticated account. The server
assigns new incidents to the user resolved from the bearer token; a supplied owner
form field cannot change that assignment. ANALYST accounts list/read only their own
incidents. ADMIN accounts list/read all incidents. Unknown and other-user incident
IDs both return the same 404 response. Anonymous requests return 401.

Legacy ownerless incidents are preserved and visible only to administrators. They
are not automatically assigned to the first account. Historical incidents keep their
original analysis JSON; their separate severity column may remain null. New completed
analyses populate severity. Public responses now include owner_user_id and severity,
but still exclude storage paths and credential hashes.

Authentication answers who the caller is. **Authorization** decides what that caller
may do. `Depends(get_current_user)` resolves identity; `Depends(require_admin)` adds
a role check. Object-level authorization adds ownership to the SQL query, before
filters or pagination. A guessed UUID cannot bypass it. Roles/active state come from
the database, so a role change affects the next request even with the same token.

## Filters and pagination

The list endpoint retains its JSON array and limit/offset interface. Limit is 1–100;
offset is nonnegative. Optional filters are status, environment, exact service_name,
severity, and inclusive created_from/created_to timestamps. Time filters require
a timezone and a valid range. Sort accepts created_at, -created_at, title, -title,
status, or -status; IDs break ties. User strings never become raw SQL sort clauses.

## Administrator tools

GET `/api/v1/admin/users` lists safe user profiles with limit/offset pagination.
PATCH `/api/v1/admin/users/{id}` accepts only role and/or is_active; empty/null
changes are rejected. Administrators cannot modify their own account through this
endpoint. PostgreSQL locks administrator rows in a stable order and rechecks the
actor before applying changes. Account deletion and password management are not added.
GET `/api/v1/admin/audit-events` lists safe audit identifiers, actions, actors,
resource references, and timestamps. Both lists default to 20 and cap at 100.

The local bootstrap command creates a new first administrator only if no ADMIN
account exists and the email is unused. It never promotes an existing account.
After bootstrap, use administrator user management for further role changes.

## Audit behavior

An **audit event** records an application action and actor. Records cover successful
registration, login, refresh, logout, incident creation, administrator bootstrap,
and user changes. They share the mutation's transaction: audit failure prevents
the change from committing. Repeated logout of an already revoked token adds no new
event. Read requests, failed login attempts, denied access, and pipeline stages are
not audited in this milestone.

Stored metadata is server-selected role/active-state changes only; never request
bodies, passwords, tokens, log content, filenames, or model input. Request IDs remain
null until Milestone 2.5. The API exposes no audit-edit endpoint; this is not a
tamper-proof or external compliance log. Authenticated API responses use no-store
cache headers.

## WSL verification — one command at a time

No new installation is needed. Run the standard checks separately:

```bash
python -m ruff format app tests scripts
python -m ruff check app tests scripts
python -m pytest -v --cov=app --cov-report=term-missing
```

The old upload/pipeline tests now authenticate against the real dependency. New tests
cover two-user isolation, owner spoofing, legacy visibility, role changes, inactive
users, filter/pagination scoping, audit rollback, and bootstrap restrictions.

Rebuild and start on the existing host port:

```bash
API_PORT=8001 docker compose up --build -d --wait
```

Then create your first administrator locally from WSL:

```bash
python -m scripts.bootstrap_admin
```

Use a new email and a private password. Password entry is hidden. Share only the
success/failure message. If an administrator already exists, use that account;
the command will refuse to create a second bootstrap administrator. No automated
account creation or promotion has been performed by the assistant.

Run the permissions smoke test:

```bash
python -m scripts.verify_permissions --admin
```

It prompts for administrator credentials privately, creates two synthetic analysts,
uploads a healthy log, and checks owner access, other-user 404/list isolation,
anonymous 401, analyst admin denial, administrator access, and a creation audit event.
It keeps tokens in memory and logs out the test refresh tokens. Two synthetic users
and one incident remain in PostgreSQL. No model call is needed. Local registration
must be enabled for this test. Without --admin it tests analyst isolation only.

For Swagger on port 8001, log in and paste the access token into Authorize privately.
An analyst sees only their incidents; an administrator can inspect the earlier
Milestone 1.7/2.1 records. Anonymous curl examples from earlier milestones now receive
401 by design. The migration history remains at `0002_normalized`.

Stop after Milestone 2.3. Multiple-file storage and cleanup workflows are Milestone 2.4;
runbook access rules will be added when runbook APIs exist.
