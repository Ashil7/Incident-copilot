# Security policy

## Supported version

This portfolio project supports the current main branch. It is a learning system and
has not received an independent security audit.

## Reporting a vulnerability

Do not open a public issue containing credentials, private logs, exploit payloads, or
personal data. Contact the repository owner privately with a minimal synthetic
reproduction, affected revision, and impact. Rotate any credential that may have been
exposed before reporting it.

## Security design

- Passwords use Argon2 hashing; access tokens are short lived and refresh tokens rotate.
- Authorization applies ownership before lookup/pagination; administrators are explicit.
- Upload extensions, content types, size, UTF-8/PDF signatures, object keys, and paths
  are validated. Storage keys and password/token hashes are never API fields.
- Known credentials and personal data are redacted before parsed log persistence or AI
  calls. Regex redaction is incomplete by nature; use synthetic data for this project.
- AI output uses strict schemas and evidence references. Uploaded logs and runbooks are
  untrusted data and cannot authorize commands. Suggested commands are display-only.
- Default tests block real provider construction. CI contains synthetic secrets only.
- Containers run as UID 10001 with dropped capabilities, no-new-privileges, and a
  read-only root filesystem. Public deployment terminates traffic at Nginx.

## Deployment responsibilities

Use HTTPS, private database/Redis networking, a random JWT signing key, restricted S3
IAM permissions, encrypted backups, security updates, and centralized secret storage.
Disable public registration unless required. Do not expose Swagger or this learning
instance publicly without additional review, rate limiting, CSRF/cookie decisions,
monitoring, and a retention policy.
