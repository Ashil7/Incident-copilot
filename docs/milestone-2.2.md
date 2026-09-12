# Milestone 2.2: authentication

Historical checkpoint: Milestone 2.3 now adds incident authorization. See
[the current permissions guide](milestone-2.3.md) for those access rules.

Implementation includes registration, JSON login, active-user lookup, rotating
refresh tokens, and logout. WSL/live verification completed on 2026-09-12.
Existing `users` and `refresh_tokens` tables are reused; no migration is required.
Local Windows Python 3.12.2 checks passed: Ruff formatting/lint and 124 tests, with
the two existing dependency deprecation warnings. No real provider calls were made.

WSL formatting and lint passed; the user reported all tests passed without supplying
a new coverage report. The user privately configured JWT_SECRET_KEY and enabled
local registration in `.env`; the assistant did not read or modify those credentials.
Both rebuilt Compose services are healthy, with the API on port 8001. The live
smoke test passed registration, login, me, refresh rotation, replay rejection, and
logout. One synthetic ANALYST account remains, as expected. Milestone 2.2 is complete;
incident ownership and permissions remain Milestone 2.3 work.

## Behavior and concepts

Passwords are hashed using pwdlib's recommended Argon2 configuration. **Hashing**
is a one-way password check; it is different from encryption. Login verifies the
stored hash and can upgrade its parameters. Unknown accounts still perform a dummy
password verification; incorrect credentials receive the same 401 response.

An **access token** is a signed JWT containing the user ID, token type, unique ID,
issue/expiry times, issuer, and audience. The signature prevents undetected changes;
the payload is readable, so it contains no password or private profile data. The API
accepts only HS256 with the configured key and checks the required claims. Default
expiry is 15 minutes. Role and active state are read from the database, not trusted
from user-supplied claims.

A **refresh token** is a random opaque secret. Only its SHA-256 hash is stored in
PostgreSQL. A fast hash is appropriate for a high-entropy random token, unlike a
human password. Refresh atomically revokes the old token and creates a new one in
the same transaction. Reuse of the old token returns 401. A failed replacement rolls
back consumption. Refresh expiry defaults to seven days from issuance, including
rotation; an active session can therefore be extended by refreshing.

**Logout** revokes the supplied refresh token and is idempotent. It does not revoke
other sessions or an already issued access token; those access tokens remain usable
until expiry. Token-family compromise detection and logout-all are not implemented.
Inactive users cannot log in, refresh, or use `/auth/me`.

`HTTPBearer` describes bearer authentication in OpenAPI and extracts the header.
`Depends(get_current_user)` validates the token and loads an active user, like a
reusable authentication helper in DRF. Synchronous `def` endpoints let FastAPI run
blocking password/SQLAlchemy work in its thread pool. Request-scoped sessions close
after the request; services explicitly commit successful authentication changes.

Registration accepts only email, password, and full name. Emails are validated and
normalized; duplicate emails return 409. Passwords accept 12–128 characters for
registration and are not trimmed. Extra fields such as `role` or `is_active` are
rejected; every public registration creates an active ANALYST. Admin assignment,
incident ownership, and permission enforcement belong to Milestone 2.3.

Authentication responses have no-store cache headers. Validation errors use a
generic message instead of echoing submitted values. Responses never expose password
or refresh-token hashes. `/auth/me` is protected; existing incident endpoints are
still public. This is not an authorization or production-deployment checkpoint.
Rate limiting, email verification, password reset, and browser login pages are not
implemented. Keep the current instance bound to loopback.

## Configuration

The API requires `JWT_SECRET_KEY` with at least 32 bytes. Use a random key, not a
memorable password. There is no default or generated-per-startup signing key.
Generate a key privately in your terminal:

```bash
python -c 'import secrets; print(secrets.token_hex(32))'
```

Copy that output into `JWT_SECRET_KEY` in your existing `.env`. Do not paste it into
chat or commit it. Add `ALLOW_REGISTRATION=true` for this local demo. Preserve all
existing PostgreSQL and model credentials. Do not copy `.env.example` over `.env`.
Leave registration false when it should be closed. Production also rejects DEBUG=true.
Changing a signing key invalidates access tokens signed with the old key; refresh
tokens are separate database-backed credentials and are not revoked by key rotation.

Optional settings: `ACCESS_TOKEN_MINUTES=15`, `REFRESH_TOKEN_DAYS=7`,
`JWT_ISSUER=incident-copilot`, `JWT_AUDIENCE=incident-copilot-api`.
Restart WSL Uvicorn or recreate the Compose API after changing settings.

## Guided checks

Run one command at a time and share only non-secret output. Start by installing
dependencies in `.venv-wsl`:

```bash
python -m pip install -r requirements-dev.txt
```

Run formatting, lint, and tests separately:

```bash
python -m ruff format app tests scripts
python -m ruff check app tests scripts
python -m pytest -v --cov=app --cov-report=term-missing
```

Tests isolate settings/database/files and block real provider calls. Authentication
tests cover registration, normalized duplicates, role injection, disabled registration,
password privacy, login, bearer validation, expired/tampered/wrong-type tokens,
issuer/audience checks, inactive users, refresh expiry/replay, rollback, and logout.

After setting the private key and local registration flag, check only booleans:

```bash
python -c 'from app.config import Settings; s=Settings(); s.validate_auth_configuration(); print("Auth configuration valid"); print("Registration enabled:", s.allow_registration)'
```

Rebuild and recreate the Compose API using port 8001:

```bash
API_PORT=8001 docker compose up --build -d --wait
```

Verify readiness:

```bash
curl -i http://127.0.0.1:8001/health/ready
```

Then run the local HTTP smoke test from WSL:

```bash
python -m scripts.verify_auth
```

The script uses a generated synthetic account and keeps its password/tokens in
memory. It checks registration, login, `/me`, refresh rotation, old-token rejection,
logout, and revoked-token rejection without printing credentials. It leaves one
synthetic ANALYST account and revoked refresh records in PostgreSQL. It uses the
development dependency httpx, so run it from WSL, not the runtime-only API image.

For manual Swagger testing at `http://127.0.0.1:8001/docs`, register an account,
then POST login with JSON `email` and `password`. Copy `access_token` into Swagger's
Authorize bearer field and execute GET `/auth/me`. Do not share the login response.
POST refresh/logout with JSON containing `refresh_token`. This is a documented JSON
login API; it is not an OAuth2 password-form token endpoint. Browser session storage
and cookie/CSRF behavior will be designed with the later UI milestone.

References: [FastAPI password hashing and JWT](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
and [PyJWT claim validation](https://pyjwt.readthedocs.io/en/stable/usage.html).
