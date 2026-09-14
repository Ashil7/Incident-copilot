# Single-host AWS EC2 deployment guide

This is a reproducible portfolio deployment plan, not an automated deployment. It does
not create paid resources. Prefer managed PostgreSQL and S3 for durable production data;
running PostgreSQL on one EC2 host shares the host's failure domain.

## Provisioning

Create an Ubuntu LTS EC2 instance only after reviewing AWS pricing. Permit SSH (22) only
from the administrator IP and HTTP/HTTPS (80/443) publicly. Do not expose 5432 or 6379.
Attach an encrypted EBS volume and an IAM role restricted to the chosen S3 bucket when
using S3. Allocate a static IP and DNS record if a stable public name is required.

Install Docker Engine from Docker's official Ubuntu repository and the Compose plugin;
verify `docker compose version`. Clone the repository into `/opt/incident-copilot`, owned
by a dedicated deploy user.

## Production configuration

Create `.env` directly on the host with mode 600. Use a random JWT secret, strong database
password, `APP_ENV=production`, `DEBUG=false`, `ALLOW_REGISTRATION=false`, explicit model
IDs, and provider credentials only when model features are enabled. For S3 set
`STORAGE_BACKEND=s3`, bucket, and region; use the instance IAM role rather than static AWS
keys. Keep `DATABASE_URL` written for the documented host workflow; container startup
rewrites only its hostname and port in memory.

Validate configuration without printing secrets:

```bash
docker compose config --quiet
```

## First start

Start dependencies, migrate with a one-off API image, then start the stack behind Nginx:

```bash
docker compose up -d --wait db redis
docker compose run --rm --no-deps api python -m scripts.migrate upgrade --container
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build --wait
```

The production override removes database, Redis, and direct API host ports and publishes
only Nginx port 80. Current Docker Compose with `!reset` tag support is required. Confirm
`/health/live`, `/health/ready`, login, worker health, and a synthetic upload.

## HTTPS

Point DNS to the host, replace `server_name _` with the domain, and use a standard ACME
client such as Certbot. Obtain the certificate using its official Nginx flow, then verify
automatic renewal with a dry run. Redirect HTTP to HTTPS and allow inbound 443 before
removing public port 80 if redirects/challenges no longer need it. Never commit private
keys or certificate material.

## Backup and restore

Schedule encrypted PostgreSQL custom-format dumps and S3 versioning/lifecycle policies.
For local storage, back up the `upload_data` volume consistently with database records.
Regularly restore into an isolated database and verify migrations and checksums; an
unrestored backup is not proven usable.

Manual database backup example:

```bash
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > incident.dump
docker compose exec -T db pg_restore --list < incident.dump > /dev/null
```

## Update

1. Record the running Git revision and image IDs.
2. Create and verify fresh database/object backups.
3. Pull the reviewed revision and build images without stopping the database.
4. Stop API and worker writers.
5. Run `python -m scripts.verify_migrations`, then the explicit migration upgrade.
6. Start with both Compose files and wait for health.
7. Run smoke checks and inspect structured logs.

## Rollback

Application rollback means checking out the recorded revision and rebuilding its images.
If its code cannot read the new schema, stop writers and use the migration's reviewed
downgrade only when it is proven data-preserving. Otherwise restore the verified database
backup and matching object-store snapshot into an isolated replacement, validate it, then
switch traffic. Never delete the current database/volume before the replacement is
verified. Record the incident and preserve logs.

Useful diagnostics:

```bash
docker compose ps
docker compose logs --tail=200 api worker db redis nginx
curl -fsS http://127.0.0.1/health/ready
```
