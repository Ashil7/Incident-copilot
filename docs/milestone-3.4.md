# Milestone 3.4: synthetic AI evaluation harness

Verified in WSL on 2026-09-13. The offline evaluator passed all eight metric groups
for three synthetic cases. Ruff formatting and linting passed, and Pytest reported
205 passed. No live provider request was needed.

Milestone 3.4 adds a repeatable evaluation dataset and report for the incident-analysis
pipeline. It changes no API, database schema, worker behavior, dependency, or secret
configuration. All default evaluation is offline and uses synthetic logs plus fixed,
reviewable structured analyses.

## What is measured

The evaluator runs each log through the real redactor, parser, signature grouper,
statistics calculator, and evidence selector. It measures:

- parser success over nonblank input lines;
- expected parsed-field accuracy;
- recall for known synthetic secrets;
- expected statistics accuracy;
- validity of observation and cause evidence IDs;
- incident-type agreement;
- the fraction of observation/cause text absent from the case's exact support allowlist;
- recall for required information gaps.

The dataset contains a healthy request, upstream HTTP failures, and an authentication
failure containing fake secrets. The committed report contains only case IDs, scores,
and optional usage measurements. It excludes logs, prompts, analyses, and secret values.

An offline score of 1.0 validates the deterministic fixtures and evaluation wiring. It
does not demonstrate live-model quality or prove that natural-language claims are true.
The unsupported-claim metric deliberately uses exact allowlisted text, so paraphrases
count as unsupported. The dataset is small and synthetic; expand it with reviewed cases
before using scores as a release threshold.

## Offline evaluation

Run this from the activated WSL environment:

```bash
python -m scripts.evaluate_ai
```

It reads `evaluations/incident_analysis.json` and replaces
`reports/offline-evaluation.json`. The default path never constructs a provider client
and cannot make a paid request. Unit tests also exercise the provider path with a mock.

## Explicit live evaluation

Live evaluation is optional and may transmit the redacted synthetic evidence to the
configured provider and incur charges. It requires both flags:

```bash
python -m scripts.evaluate_ai --live --confirm-cost --output reports/live-evaluation.json
```

Live reports add provider-reported input/output token counts and request duration per
case. Missing usage remains null. The report still omits provider output and payloads.
Do not commit live reports unless they have been reviewed for the intended repository.

Pin model versions when reproducibility matters and rerun evaluations when prompts,
models, parsing, redaction, evidence selection, or schemas change. OpenAI's evaluation
API provides managed datasets, runs, and graders for larger suites; this milestone uses
a local transparent harness so it remains vendor-neutral and works without credentials.

## Verification

Run each command separately:

```bash
python -m scripts.evaluate_ai
```

```bash
python -m ruff format app tests scripts
```

```bash
python -m ruff check app tests scripts
```

```bash
python -m pytest -v
```

No Docker rebuild or live provider call is needed. Stop after Milestone 3.4.

Official reference: [OpenAI Evals API](https://developers.openai.com/api/reference/resources/evals/methods/create).
