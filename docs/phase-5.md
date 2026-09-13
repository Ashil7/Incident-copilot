# Phase 5: user experience and reporting

Phase 5 implements Milestones 5.1 through 5.4 as one integrated checkpoint.
Verified on 2026-09-13. Ruff formatting and linting passed, and the full suite reported
216 tests passed in local Windows and WSL environments. All rebuilt Compose services
are healthy. Browser verification passed login, dashboard, incident details, event
filters, similarity, resolution and feedback controls. The downloaded RCA PDF opened
successfully with all required sections. This phase adds no migration and leaves the
database at `0005_phase4_retrieval`. No `.env` credential was read or changed.

## 5.1: application shell and authentication

Jinja2 renders lightweight HTML page shells and Bootstrap supplies responsive styles.
Minimal vanilla JavaScript calls the existing JSON authentication API. Access and
refresh tokens are stored in browser session storage, which clears when the browser
session ends. API values are inserted with `textContent` rather than executable HTML.
An expired or invalid access token clears browser state and redirects to sign-in.

This learning UI does not yet rotate the refresh token automatically and does not use
secure server-side cookie sessions. Bootstrap CSS loads from a CDN, so the pages remain
functional but unstyled if that CDN is unavailable.

## 5.2: dashboard and incident workflow

The dashboard shows actual recent incidents and their processing state. It has a clear
empty state and links to multi-file synthetic log upload. After creation, the incident
page polls while work is active and displays a controlled retry action after failure.
No decorative or fabricated operational metric is shown.

## 5.3: analysis and retrieval views

The incident page labels AI-generated analysis, displays deterministic statistics and
evidence, and provides event filters for level, HTTP status, endpoint substring, and
evidence-only records. The API also accepts timezone-aware event ranges and a bounded
result limit. Similar incident results retain descriptive similarity labels and show a
human-confirmed resolution when one exists.

The runbook page uploads `.txt`, `.md`, or text-based `.pdf` documents, shows indexing
states, and supports reindex/delete actions. Questions return citation title, bounded
excerpt, and page/section metadata from the Phase 4 API. Uploaded instructions remain
untrusted data.

## 5.4: resolution, feedback, and PDF report

Resolution and feedback forms call the ownership-protected Phase 4 endpoints. Human
root cause and resolution remain distinct from AI possible causes. The authenticated
RCA PDF includes a UTC generation timestamp, incident metadata/window, human-confirmed
fields, clearly labeled AI analysis, calculated statistics, evidence source/line data,
possible causes, diagnostic checks and risk labels, information gaps, and similar
resolved incidents when available.

PDF strings and list counts are bounded before drawing. ReportLab draws strings as text,
so uploaded markup is not interpreted. Tests reopen the PDF with PyPDF and confirm key
sections. The report is generated synchronously; a report job/queue is a later scaling
improvement.

## Browser routes

| Path | Page |
| --- | --- |
| `/login` | Sign in |
| `/register` | Optional public registration |
| `/` | Incident dashboard |
| `/incidents/new` | Incident and log-file creation |
| `/incidents/{id}` | Polling, analysis, events, similarity, resolution, feedback, PDF |
| `/runbooks` | Runbook management and cited questions |

The supporting API additions are `GET /api/v1/incidents/{id}/events` and
`GET /api/v1/incidents/{id}/report.pdf`. Both use existing bearer authentication and
object ownership rules.

## Verification

Run separately in WSL:

```bash
python -m pip install -r requirements.txt
python -m ruff format app tests scripts
python -m ruff check app tests scripts
python -m pytest -v
API_PORT=8001 docker compose up --build -d --wait
curl -I http://127.0.0.1:8001/login
```

Then open `http://127.0.0.1:8001/login`, sign in with the existing local account, and
use synthetic data to inspect the workflow. Runbook indexing and answers require a
configured provider and may incur charges; they are not required for offline Phase 5
verification. Stop after Phase 5.
