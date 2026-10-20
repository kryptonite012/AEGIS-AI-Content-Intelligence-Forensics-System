<div align="center">

<img src="apps/web/src/app/icon.svg" width="76" alt="AEGIS logo" />

# AEGIS

**Advanced Evidence, Generation Intelligence & Synthetic-Media Forensics System**

A multimodal forensic workstation that helps authorised analysts examine whether text, images, audio or video may have been generated or materially altered by AI. It reports only what the evidence supports.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.143-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-15.5-000000?logo=nextdotjs&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Tests](https://img.shields.io/badge/tests-101%20py%20·%203%20unit%20·%203%20e2e%20passing-34D399)
![License](https://img.shields.io/badge/license-MIT-blue)

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/kryptonite012/AEGIS-AI-Content-Intelligence-Forensics-System)

</div>

<p align="center"><img src="docs/assets/screenshot-overview.png" alt="AEGIS overview dashboard" width="100%" /></p>

**Contents:** [What it does](#what-it-does) · [Run it](#run-it) · [Sign in](#sign-in) · [Screens](#screens) · [What works today](#what-works-today) · [Architecture](#architecture) · [Development](#development) · [Documentation](#documentation) · [Responsible use](#responsible-use)

## What it does

AEGIS manages an investigation from start to finish: open a case, acquire evidence with hashing and write-once storage, run the analysis methods for each media type, have an independent reviewer decide, and export a verifiable report. Every step is recorded in a hash-chained audit trail.

Its results fall into **seven evidence classes**. AEGIS never mixes them up or averages them together:

| Evidence class | Meaning | In AEGIS |
| --- | --- | --- |
| Statistical inference | How closely content resembles known AI output. **Not proof of authorship.** | Classifier, token statistics, Fast-DetectGPT, Binoculars (these need model weights to run) |
| Watermark verification | A keyed test for one specific watermark scheme | AEGIS reference green-list watermark (Kirchenbauer et al., 2023), exact binomial p-values |
| Signed provenance | A cryptographic check of a signed record. A valid signature does not make the record's claims true. | C2PA Content Credentials, checked with the official `c2pa-rs` library |
| Forensic observation | Measurements for an analyst; not a classifier | EXIF/ICC/JPEG tables, frequency spectrum, noise residual, ELA, spectrograms, video timelines |
| Declared metadata | Unsigned claims in the file, which anyone can edit | PNG text chunks, EXIF Software, XMP DigitalSourceType |
| Process evidence | Drafts, revision history and notes | Evidence uploaded with the `process_evidence` role |
| Human assessment | A qualified reviewer's conclusion | A review decision that is hashed and recorded in the audit trail |

**Rules the system enforces:**
- A detector flag **starts a review**. It never establishes misconduct.
- A low score does not prove a human wrote the content.
- A missing watermark or provenance record proves nothing either way.
- A method that cannot run reports `unavailable`. A method that crashes reports `failed`. Neither ever produces a score.
- Fusion (`aegis-fusion-v1`) reports disagreeing methods as a contradiction, never as an average.
- The research bench uses Bayes to show how base rates change what a flag is worth (PPV). True-positive rates at a strict false-positive rate are reported only when the sample is large enough to estimate them.

## Run it

| Option | Best for | You need |
| --- | --- | --- |
| **[A. Render](#a-render-free-public-link)** | A free public `https://….onrender.com` link for demos | A GitHub and a Render account |
| **[B. Docker Compose](#b-docker-compose)** | The full stack on one machine or a server | Docker 24+ with Compose v2 |
| **[C. Local development](#c-local-development)** | Changing the code | Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 22, pnpm 10, PostgreSQL 16, Redis 7, ffmpeg |

### A. Render (free public link)

1. Click **Deploy to Render** above. Alternatively, in Render choose **New → Blueprint**, then select this repository and the `main` branch.
2. When asked for `AEGIS_DEMO_PASSWORD`, enter a private password of at least 12 characters.
3. Click **Apply** and wait 10–15 minutes for the first build. The service is ready when its log shows `Demo organisation and DEMO FIXTURE cases are ready.`

A Render deployment is one free web service, with evidence stored in PostgreSQL and analyses running in process. It can run alongside your other Render projects. If your free Render database is already in use, use the Neon variant (`infrastructure/render/render-external-database.yaml`). See the **[Render guide](docs/operations/render.md)** for limits, measurements and troubleshooting. This mode is for demos with synthetic data only.

### B. Docker Compose

```bash
cp .env.example .env                                   # set AEGIS_SECRET_KEY to a long random value
docker compose up --build -d                           # postgres, redis, migrate, api, worker, beat, web
docker compose exec api python -m app.cli seed-demo    # demo users and DEMO FIXTURE cases (not in production)
# open http://localhost:3000
```

To serve a shared machine over HTTPS (for example a college server), run `scripts/server-setup.sh` and see the [college server guide](docs/operations/college-server.md). For production settings, see the [deployment guide](docs/operations/deployment.md).

### C. Local development

```bash
make setup       # locked Python and Node dependencies, creates .env
make services    # PostgreSQL and Redis in Docker (or use local ones)
make migrate     # Alembic migrations + roles and model registry
make seed-demo   # demo organisation, one user per role, three DEMO FIXTURE cases
make dev         # API on :8000 (OpenAPI at /api/docs), Celery worker, web on :3000
```

## Sign in

The demo seeder creates one account per role. All of them use the same password.

| Account | Role | Can do |
| --- | --- | --- |
| `investigator@aegis.demo` | Investigator | Open cases, acquire evidence, run analyses, draft reports. **Start here.** |
| `analyst@aegis.demo` | Forensic analyst | Perform analyses and research evaluations |
| `reviewer@aegis.demo` | Independent reviewer | Review evidence and record the human assessment (separation of duties) |
| `auditor@aegis.demo` | Auditor | Read-only access to cases, reports and the audit trail |
| `researcher@aegis.demo` | Read-only researcher | Research bench and benchmark results only; no case data |
| `orgadmin@aegis.demo` | Organisation admin | The organisation's users, settings and models |
| `admin@aegis.demo` | System administrator | Full access, including system settings |

**Password**
- **Render:** the `AEGIS_DEMO_PASSWORD` you entered. To view it, open the service → **Environment**. Editing it later does not change accounts that already exist.
- **Compose / local:** the value of `AEGIS_DEMO_PASSWORD` in `.env`. The default is `Aegis-Demo-Only-2026`, and it is refused on Render.
- **Locked out:** after 10 failed attempts in a row an account is locked for 15 minutes.
- **Production:** demo seeding is refused when `AEGIS_ENVIRONMENT=production`. Create a real administrator with `python -m app.cli create-admin`.

## Screens

| | |
| --- | --- |
| <img src="docs/assets/screenshot-case-analysis.png" alt="Case analysis" /> **Case workspace:** automated assessment, unavailable methods with reasons, results grouped by evidence class | <img src="docs/assets/screenshot-research.png" alt="Research bench" /> **Research bench:** Bayes positive-predictive-value calculator with labelled input sources, and the nine reliability experiments |
| <img src="docs/assets/screenshot-benchmarks.png" alt="Benchmark laboratory" /> **Benchmark laboratory:** simulated results labelled as such, exact confidence intervals, checks on whether a strict false-positive rate can be estimated | <img src="docs/assets/screenshot-image.png" alt="Image forensics" /> **Image forensics:** provenance, metadata and visualisations, each stating what it *cannot* establish |
| <img src="docs/assets/screenshot-provenance.png" alt="Provenance" /> **Provenance & watermarks:** signature validity, signer trust and truth of claims kept apart | <img src="docs/assets/screenshot-health.png" alt="System health" /> **System health:** live component checks and the true status of every method |

## What works today

| Capability | Status |
| --- | --- |
| Cases: state machine, separation of duties, appeals, corrections | ✅ Operational, tested |
| Evidence vault: content sniffing, SHA-256, write-once storage (local / S3 / PostgreSQL), versions, redaction, integrity alerts, two-person deletion | ✅ Operational, tested (S3 against moto) |
| Text extraction (TXT, PDF, DOCX), segmentation, language ID including Hindi and other Indic scripts | ✅ Operational, tested |
| C2PA Content Credentials verification | ✅ Tested with signed, tampered and unsigned files |
| AEGIS reference text watermark verifier | ✅ Verifies text from the AEGIS reference generator under this deployment's key only |
| Image, audio and video forensic observations (Pillow, NumPy/SciPy, ffmpeg) | ✅ Operational, tested |
| Reports: deterministic PDF + canonical JSON with SHA-256, re-verifiable | ✅ Operational, tested |
| Security: Argon2id, JWT + revocable sessions, rotating refresh cookie, TOTP MFA, RBAC (7 roles, 32 permissions), tenant isolation, rate limits, hash-chained audit | ✅ Operational, tested |
| Supervised, token-statistic, Fast-DetectGPT and Binoculars text detectors | ⚠️ Adapters implemented; **no model weights are bundled**, so these report `unavailable` until configured |
| Synthetic-speech and image classifiers (ONNX), external provider services | ⚠️ Integration points; run once a model or authorised provider is configured |
| SynthID-Text and other provider watermarks | ⛔ Placeholder: needs a provider agreement, keys and detector weights |
| Calibrated probabilities and validated thresholds | ⛔ None: no detector has been validated on locally measured real data |

Full list: [limitations and residual risks](docs/governance/limitations-and-residual-risks.md). To enable model-backed methods, see [configuring detectors](docs/operations/configuring-detectors.md).

## Architecture

| Layer | Technology |
| --- | --- |
| Web | Next.js 15 (App Router), React 18, Tailwind, TanStack Query/Table, Recharts |
| API | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, server-sent job events |
| Jobs | Celery + Redis with late acknowledgement and idempotent runs. Inline mode for single-container hosts. |
| Analysis | `aegis_ml` (methods, sniffing, C2PA, fusion) and `aegis_research` (reliability statistics, watermark, experiments) |
| Storage | Write-once and content-addressed, on local disk, S3 or PostgreSQL |

```
apps/api/        FastAPI service, models, migrations, Celery tasks, CLI, tests
apps/web/        Next.js workstation and Playwright tests
ml/              aegis_ml: analysis methods, content sniffing, C2PA, providers, fusion
research/        aegis_research: reliability statistics, reference watermark, nine experiments
packages/        shared TypeScript API types
infrastructure/  Dockerfiles, Caddy/server and Render deployment files
docs/            architecture, security, API, research, operations, governance
scripts/         dev runner, server setup, load test
render.yaml      Render Blueprint
```

Diagrams and design decisions: [architecture overview](docs/architecture/overview.md).

## Development

| Command | Purpose |
| --- | --- |
| `make test` | Python tests (research, ML, API on PostgreSQL) plus web unit tests and type check |
| `make test-e2e` | Playwright browser tests against a running, seeded stack |
| `make lint` / `make format` | Ruff and ESLint |
| `make benchmark` / `make experiments` | Simulated benchmark and the nine experiments (`benchmarks/runs/`, `research/results/`) |
| `make verify` | Recompute every evidence hash and verify the audit chain |
| `make security-check` | pip-audit, pnpm audit, CycloneDX SBOM |
| `make loadtest` | Repeatable API load test ([results](docs/operations/performance.md)) |
| `make build` / `make up` / `make down` | Container images and the Compose stack |

Settings come from `AEGIS_*` environment variables. [`.env.example`](.env.example) documents each one. With `AEGIS_ENVIRONMENT=production`, the API refuses to start with the development secret key, inline jobs or insecure cookies.

## Documentation

| Area | Documents |
| --- | --- |
| Architecture | [overview](docs/architecture/overview.md) · [data model](docs/architecture/data-model.md) · [decisions](docs/architecture/decisions.md) |
| Security | [threat model](docs/security/threat-model.md) · [controls](docs/security/security-controls.md) · [audit chain](docs/security/audit-chain.md) |
| API | [guide](docs/api/README.md) · [provider contract](docs/api/provider-contract.md) · OpenAPI at `/api/docs` |
| Research | [methods & literature](docs/research/methods-and-literature.md) · [evaluation](docs/research/evaluation-methodology.md) · [experiments](docs/research/experiments.md) · [model cards](docs/research/model-cards.md) · [dataset cards](docs/research/dataset-cards.md) · [multilingual plan](docs/research/multilingual-evaluation-plan.md) · [independent evaluation](docs/research/independent-evaluation-protocol.md) |
| Operations | [Render](docs/operations/render.md) · [college server](docs/operations/college-server.md) · [deployment](docs/operations/deployment.md) · [detectors](docs/operations/configuring-detectors.md) · [backup](docs/operations/backup-and-recovery.md) · [incidents](docs/operations/incident-response.md) · [performance](docs/operations/performance.md) · [troubleshooting](docs/operations/troubleshooting.md) |
| Governance | [pilot readiness](docs/governance/README.md) · [compliance mapping](docs/governance/compliance-mapping.json) · [review & appeal](docs/governance/human-review-and-appeal-procedure.md) · [roadmap](docs/governance/roadmap.md) |

## Responsible use

AEGIS is defensive investigative software. It has no surveillance, account-access or device-monitoring features. It performs no biometric identification, and it never infers a person's identity, nationality, ethnicity or intent. It holds no government approval or certification and claims none. Any operational deployment needs a legal, privacy and security review first. **A detector score alone must never lead to punishment, rejection, prosecution or any other adverse decision about a person.**

## License

[MIT](LICENSE)
