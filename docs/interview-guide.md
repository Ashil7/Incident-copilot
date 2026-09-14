# Interview guide

## Two-minute explanation

The Incident Copilot accepts synthetic logs, stores files behind an adapter, and queues
durable Celery jobs. Python redacts and parses events, calculates statistics, and selects
bounded evidence. An AI provider explains that evidence through a strict schema; it does
not calculate metrics or confirm root cause. PostgreSQL stores job progress, validated
analysis, audits, and pgvector embeddings. Runbook answers require retrieved citations,
similar incidents remain owner-scoped, and humans provide the confirmed resolution.

## Design questions

1. **Why synchronous SQLAlchemy?** It keeps the learning architecture understandable;
   Celery handles long work. Each request/task owns and closes its session.
2. **Why PostgreSQL plus Redis?** PostgreSQL owns durable state and constraints. Redis
   transports small task identifiers. Losing Redis does not erase incident records.
3. **How are duplicate jobs prevented?** A partial unique index allows one active job per
   incident, row locks serialize scheduling, and advisory locks fence worker execution.
4. **Why deterministic evidence first?** It bounds cost/context and lets code validate
   every model citation against persisted facts.
5. **What does pgvector similarity mean?** It ranks semantic proximity; descriptive
   labels avoid presenting it as causal confidence.
6. **How is prompt injection handled?** Uploaded text is labeled untrusted, tools are not
   exposed, prompts forbid document instructions, and outputs/citations are validated.
7. **Why exact vector search?** The demo dataset is too small to justify HNSW. Add an
   approximate index only after measuring recall, latency, and build/storage cost.
8. **How would this scale?** Managed PostgreSQL/S3/Redis, multiple workers, async report
   jobs, retention policies, metrics/alerts, and load-tested connection/task limits.
9. **Main limitations?** Regex redaction gaps, no OCR, no organization tenancy, no live
   streaming/remediation, session-storage browser auth, and provider calls may repeat
   across a crash before commit.
