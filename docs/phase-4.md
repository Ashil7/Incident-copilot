# Phase 4: retrieval features

Phase 4 implements Milestones 4.1 through 4.4 as one integrated checkpoint. Verified
on 2026-09-13. Ruff formatting and linting passed, and the full suite reported 213
tests passed in both local Windows and WSL environments. The fresh/legacy PostgreSQL
migration verifier passed, the application schema reached `0005_phase4_retrieval`, and
the rolled-back retrieval smoke test passed vector extension, 1,536-dimension storage,
exact runbook retrieval, and owner-scoped similar incidents. All four Compose services
are healthy; the worker responded and registered `runbook.index`. No `.env` credential
was read or changed, and no live provider call was made.

## 4.1: pgvector and embeddings

Migration `0005_phase4_retrieval` enables PostgreSQL's `vector` extension and adds
`runbooks`, `runbook_chunks`, and `incident_embeddings`. Vector columns are exactly
1,536 dimensions, matching the required `EMBEDDING_DIMENSIONS=1536` setting. The
default model is `text-embedding-3-small`; changing dimensions requires a reviewed
migration. PostgreSQL performs exact cosine-distance queries. SQLite tests store
vectors as JSON and calculate cosine similarity in Python.

An **embedding** is a numeric representation of text. Nearby vectors often represent
related text. A cosine score describes vector closeness; it is retrieval ranking, not
confidence or proof. No HNSW index is added because this dataset is not yet large
enough to measure whether approximate search helps.

## 4.2: runbook ingestion

Authenticated users can upload `.txt`, `.md`, and `.pdf` runbooks. The service checks
extension/MIME pairs, streams size enforcement, rejects empty or invalid UTF-8 text,
uses an opaque UUID storage key, calculates SHA-256, and omits storage details from
responses. Only administrators may mark a runbook global. Analysts see their own and
global runbooks.

Celery receives only runbook and request IDs. The worker extracts text, preserves PDF
page numbers, normalizes whitespace, redacts recognized secrets, creates overlapping
chunks, generates embeddings in a batch, and replaces chunks transactionally. Safe
PENDING, INDEXING, READY, and FAILED states are public. Regex redaction cannot guarantee
removal of every secret, so use synthetic runbooks only.

## 4.3: cited questions

`POST /api/v1/runbooks/ask` embeds the question and retrieves accessible READY chunks
above the configured threshold. If nothing qualifies, it returns a deterministic
insufficient-context response and skips the answer model. Otherwise the provider must
return structured citations to retrieved chunk IDs. Unknown or missing citations are
rejected. Returned citations include title, chunk ID, page/section metadata, and a
bounded excerpt. The versioned prompt treats document instructions as untrusted data.

## 4.4: similar incidents, resolution, and feedback

Completed or human-resolved incidents can receive a redacted searchable representation
containing service, incident type/summary, error signatures, and confirmed resolution.
Exact search is owner-scoped, excludes the current incident, returns at most five, and
uses descriptive labels: `very similar`, `similar`, or `possibly related`. Results with
human-confirmed resolution sort before unresolved results. Resolution and feedback
mutations create audit events. Human-confirmed text stays distinct from AI suggestions.

## Endpoints

| Method and path | Behavior |
| --- | --- |
| POST `/api/v1/runbooks` | Store and queue a runbook; 202 |
| GET `/api/v1/runbooks` | List owned and global runbooks |
| GET `/api/v1/runbooks/{id}` | Retrieve accessible metadata |
| DELETE `/api/v1/runbooks/{id}` | Delete an authorized runbook; 204 |
| POST `/api/v1/runbooks/{id}/reindex` | Queue replacement indexing; 202 |
| POST `/api/v1/runbooks/ask` | Retrieve context and return a cited answer |
| GET `/api/v1/incidents/{id}/similar` | Owner-scoped exact similarity results |
| PATCH `/api/v1/incidents/{id}/resolution` | Save human-confirmed resolution |
| POST `/api/v1/incidents/{id}/feedback` | Save user feedback; 201 |

## Upgrade and verification

This phase changes the PostgreSQL image from `postgres:16` to
`pgvector/pgvector:pg16`. It preserves the existing PostgreSQL 16 named volume. Take
and verify a fresh custom-format backup before recreating services. Stop API and worker
writers, pull/start the database, run migration verification, upgrade the application
schema, then rebuild all services. Execute each README command separately.

Default automated tests block live providers. Runbook indexing and question answering
need valid provider configuration for a live smoke test and can incur embedding/model
charges. Do not enable that test merely to complete the offline checkpoint.

Operational limits: indexing has no durable job table yet; FAILED runbooks require the
explicit reindex endpoint. PDF extraction supports text PDFs, not OCR. Deletes remove
the local object after the database commit, so an object-store failure requires storage
operator cleanup. Similar-incident indexing is best effort and may require resolution
resubmission if the provider is unavailable.

Official references: [pgvector exact search](https://github.com/pgvector/pgvector#querying)
and [OpenAI embeddings](https://platform.openai.com/docs/guides/embeddings).
