# Milestone 3.3: provider interface and validated analysis records

Verified on 2026-09-13. Local Ruff formatting and linting passed;
Pytest reported 198 passed with two existing dependency deprecation warnings.
The user reported 198 tests passed in WSL, and all four rebuilt Docker services are
healthy. Live deterministic verification passed job progress, retry eligibility,
explicit reanalysis, and normalized provider metadata. It retained synthetic incident
`fb3a4c51-395c-4b55-a1a0-66096bb72105`. Reviewed worker logs show two distinct job
and request IDs for that incident and contain no prompt, raw uploaded content,
credentials, model response, or token payload. No database migration, dependency install,
or `.env` credential change is required. The schema remains `0004_analysis_jobs`.

## What changed

The pipeline now calls a provider-neutral `AIProvider` contract. It defines
`analyze_incident`, `answer_runbook_question`, and `create_embeddings`; the latter
two reserve the common boundary for later retrieval milestones. The OpenAI adapter
is the only infrastructure module that imports and calls the OpenAI SDK. The earlier
`llm_service.generate_analysis` function remains as a compatibility facade and
delegates to that adapter.

An **interface** states what the pipeline needs without coupling it to one vendor.
An **adapter** translates that interface into a provider SDK call. This keeps mocked
offline tests simple and allows a future provider to be selected without putting SDK
details into parsing, evidence, or job code.

The current OpenAI adapter uses the Responses API structured-output parser with the
strict Pydantic `IncidentAnalysis` schema. It sends only redacted statistics and
selected evidence, supplies no tools, disables response storage with `store=False`,
and disables SDK retries because durable jobs own the attempt budget. The model comes
from `LLM_MODEL`, with `OPENAI_MODEL` retained as a compatibility fallback; business
logic does not hardcode a model.

## Versioned prompts

`prompt_registry.py` maps an allowlisted version to a packaged UTF-8 file. The active
version is `incident_analysis_v1`. Arbitrary paths and unknown versions are rejected,
and empty prompt files fail before a provider call. A prompt version is immutable in
practice: change behavior by adding a new file and allowlist entry rather than editing
an old production version. Existing `incident_analysis_v1.txt` is preserved.

The prompt treats every supplied label and log message as untrusted data, forbids
confirmed-root-cause language, requires evidence citations for observations and
possible causes, and describes suggested commands as display-only human checks.
Prompt text and raw model input/output are never written to logs.

## Persistence and validation

Every successful analysis is stored in `incident_analyses`, including deterministic
no-evidence results. The normalized row records provider, configured model, prompt
version, structured result, input/output token counts when available, duration, and
creation time. The legacy `incidents.analysis` JSON remains populated for backward
compatibility. Reanalysis creates another immutable history row; `GET
/api/v1/incidents/{id}/analysis` returns the newest authorized row.

The endpoint omits internal job and storage details. Analysts can read only their own
incident analysis; administrators retain cross-owner access. A missing incident or
cross-user request returns 404. An incident without a successful normalized result
also returns 404.

Provider output passes these checks before persistence:

- Strict schema fields; unknown fields are rejected.
- Bounded, nonempty title, type, summary, observations, causes, and checks.
- Severity and command-risk enums, finite confidence from 0 through 1.
- Unique, nonempty affected components and information gaps.
- Consecutive recommendation order starting at 1.
- At least one evidence citation on every observation and possible cause.
- No duplicate or unknown evidence references.
- A second validation after redacting provider output.

Unsupported or malformed output is a permanent job failure and is not retried
automatically. Validation proves references point to selected evidence; it cannot
prove that every natural-language claim is logically entailed by that evidence.
That measured evaluation belongs to Milestone 3.4. Suggested commands are returned
as text and are never executed.

## Usage semantics and limits

For OpenAI responses, `input_tokens` and `output_tokens` come from the response usage
object when present. Duration measures the SDK call around the Responses API request.
The normalized row records the exact configured model string returned by the adapter
and the selected local prompt version. Missing usage remains null rather than being
estimated. Deterministic no-evidence analysis uses provider `deterministic`, no model
or prompt, null token counts, and zero duration.

The current provider call can repeat after a worker crash before its database commit,
as documented in Milestone 3.2. Token counts are per successfully persisted provider
response, not an account billing report and not a record of failed or lost attempts.
No live provider evaluation is part of this milestone.

## Verification, one command at a time

```bash
python -m ruff format app tests scripts
```

```bash
python -m ruff check app tests scripts
```

```bash
python -m pytest -v
```

Default tests block real SDK construction. Mocked tests verify the provider interface,
prompt allowlist, Responses API arguments, configured model, prompt version, usage
mapping, output validation, redaction, normalized persistence, and ownership.

Since there is no migration, rebuild the API and worker after tests:

```bash
API_PORT=8001 docker compose up --build -d --wait
```

Run the existing deterministic smoke test:

```bash
python -m scripts.verify_jobs
```

It now also verifies the normalized analysis endpoint and metadata without requiring
an API key or making a paid provider call. Existing credentials are entered privately.
Inspect no secrets or response payloads in worker logs:

```bash
docker compose logs --tail=40 worker
```

Stop after Milestone 3.3. Offline evaluation datasets and reports begin in 3.4.

Official reference: [OpenAI Responses API reference](https://platform.openai.com/docs/api-reference/responses).
