# API guide

- **Base path:** `/api/v1`. The interactive OpenAPI UI is at `/api/docs` (ReDoc at `/api/redoc`), and the machine-readable spec is at `/api/openapi.json`.
- **Snapshot:** a copy of the spec for this release is in [`openapi.json`](openapi.json). It covers 92 paths and 105 operations.

## Conventions

| Topic | Behaviour |
| --- | --- |
| Authentication | `POST /auth/login` → `{access_token, expires_in}`. The refresh token is set as an httpOnly cookie. Send `Authorization: Bearer <token>`. `POST /auth/refresh` requires the cookie and `X-Requested-With: aegis-web`. |
| Organisation | Requests run in the caller's first membership by default. Use `X-AEGIS-Organization: <uuid>` to select another; non-members get 403. |
| Errors | `{"error": {"code", "message", "correlation_id", "details"}}`. Codes include `unauthenticated`, `forbidden`, `not_found`, `validation_error`, `conflict`, `invalid_transition`, `unsupported_media`, `malformed_media`, `payload_too_large`, `rate_limited`, `malware_detected`. |
| Correlation | Every response carries `X-Request-ID`. A valid incoming `X-Request-ID` is propagated to logs and audit events. |
| Pagination | `GET /investigations?page=&page_size=` returns `{items, total, page, page_size}`. Filters: `status` (comma-separated), `priority`, `q`, `assigned_to_me`. Sorting: `sort=updated_at\|created_at\|priority\|title&order=asc\|desc`. |
| Idempotency | `POST /analysis/investigations/{id}/jobs` accepts `Idempotency-Key`. Repeating the key returns the original job. |
| Rate limits | Login: 10/min per IP+email. Uploads: 120/hour per user. API: 600/min per user. A breach returns 429 `rate_limited`. All are configurable. |
| Hash headers | Evidence downloads, artefacts and report PDFs include `X-AEGIS-SHA256`. |
| Live progress | `GET /analysis/jobs/{id}/events` is a `text/event-stream` of persisted job snapshots. It emits only on change and closes when the job reaches a terminal state. |

## Endpoint families

| Family | Main operations |
| --- | --- |
| `/auth` | login, refresh, logout, me, change-password, MFA setup/enable, sessions list/revoke |
| `/investigations` | list/create/get/patch, transition, assign, legal-hold, annotations, reviews, appeals (+ resolve), deletion requests (+ decide), history, reviewers |
| `/investigations/{id}/evidence`, `/investigations/{id}/uploads`, `/uploads/{id}` | multipart upload, chunked upload (init → PUT chunks with `offset` → complete) |
| `/evidence` | cross-case list (`modality=text,document\|image\|audio\|video` serves the Text/Image/Audio/Video forensics views), get, version download, thumbnail, extracted text, verify integrity, redactions |
| `/analysis` | profiles, create job, list jobs, get job (runs, artefacts, fusion), cancel, SSE events, run segments |
| `/artifacts/{id}` | forensic visualisations (PNG) |
| `/provenance/records`, `/watermarks/verifiers` | provenance verification records; verifier capability list |
| `/detectors`, `/models` | method capability and availability; model registry (PATCH audited; validation requires benchmark evidence) |
| `/reports` | generate, list, JSON export, PDF export, finalise, verify, corrections |
| `/evaluation` | PPV calculator, threshold explorer, fairness, robustness, experiments (list/run/history) |
| `/benchmarks` | datasets (register/list), runs (create/list/get/samples), built-in reference-watermark benchmark, imported scores, calibration profiles |
| `/audit` | events, verify chain, chain head |
| `/users`, `/roles`, `/organizations`, `/admin/*`, `/governance/*` | administration, settings, retention, stale-job recovery, compliance mapping |
| `/health` | `live` (no auth), `ready` (database + storage), `components` (authenticated: infrastructure, methods, queue) |

The specification suggested separate `/text`, `/images`, `/audio` and `/video` route families. AEGIS serves those views through the single `/evidence?modality=` family, so evidence access control is enforced in one place. Modality-specific results are part of each analysis job.

## Example

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"investigator@aegis.demo","password":"Aegis-Demo-Only-2026"}' | jq -r .access_token)
H="Authorization: Bearer $TOKEN"
CASE=$(curl -s localhost:8000/api/v1/investigations -H "$H" -H 'Content-Type: application/json' \
  -d '{"title":"API example","case_reference":"API-1","purpose":"Demonstrate the API workflow.","media_category":"text"}' | jq -r .id)
EV=$(curl -s localhost:8000/api/v1/investigations/$CASE/evidence -H "$H" -F file=@notes.txt | jq -r .id)
JOB=$(curl -s localhost:8000/api/v1/analysis/investigations/$CASE/jobs -H "$H" -H 'Content-Type: application/json' \
  -d "{\"evidence_item_id\":\"$EV\",\"profile_id\":\"text_triage\"}" | jq -r .id)
curl -sN localhost:8000/api/v1/analysis/jobs/$JOB/events -H "$H"     # live state until terminal
curl -s localhost:8000/api/v1/analysis/jobs/$JOB -H "$H" | jq .fusion
```
