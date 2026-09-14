# Phase 6: release readiness and portfolio handoff

Phase 6 turns the verified learning application into a reviewable release candidate.
It adds a CI quality gate, a multi-stage non-root image, optional S3 object storage,
a production Compose/Nginx example, deployment and recovery instructions, an
idempotent synthetic demo seeder, security notes, architecture documentation, and
interview preparation. It does not deploy infrastructure or use paid cloud services.

## Milestone map

- **6.1:** GitHub Actions runs Ruff, Alembic migration verification, tests, coverage,
  and a Docker build check with PostgreSQL/pgvector and Redis services.
- **6.2:** Containers use an unprivileged user and hardened Compose settings. Local
  storage remains the default; `STORAGE_BACKEND=s3` selects private S3-compatible
  storage through the standard AWS credential chain.
- **6.3:** `docker-compose.production.yml`, `deploy/nginx.conf`, and
  `docs/deployment.md` describe a single-host EC2 deployment, HTTPS termination,
  backup/restore, updates, and rollback.
- **6.4:** `scripts.seed_demo` creates two idempotent synthetic resolved incidents.
  The final README, architecture, security, screenshot checklist, and interview guide
  make design decisions and limitations easy to review.

No schema migration is introduced. Revision `0005_phase4_retrieval` remains current.
Use only synthetic demo data and never capture tokens, passwords, `.env` values, or
real incident content in screenshots.

## Verification

Run the following independently in the WSL environment:

```bash
python -m ruff format app tests scripts
python -m ruff check app tests scripts
python -m pytest -v --cov=app --cov-report=term-missing
python -m scripts.verify_migrations
docker compose config --quiet
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
docker build --check .
```

After Compose is healthy, seed an existing local analyst or administrator account:

```bash
python -m scripts.seed_demo --email YOUR_ACCOUNT_EMAIL
```

The command is safe to repeat. It prints counts and never asks for or prints a
password. Deployment steps are deliberately manual and are documented in
`docs/deployment.md` so no cloud resource is created by this repository.

## Verified checkpoint

Verified in WSL on 2026-09-14: 220 tests passed; migration verification passed for
fresh and legacy schemas; both Compose configurations parsed; `docker build --check`
reported no warnings; the rebuilt API, worker, PostgreSQL, and Redis services were
healthy; readiness returned HTTP 200; the API ran as UID/GID 10001; and repeating the
demo seed reported two existing records with no duplicates. The optional production
Nginx deployment and live S3/AWS path remain environment-specific operator checks.
