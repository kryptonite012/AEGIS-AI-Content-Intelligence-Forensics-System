# Architecture overview

AEGIS is a modular monorepo with four layers, kept deliberately separate:

| Layer | Package | Responsibility |
| --- | --- | --- |
| Research | `research/aegis_research` | Pure statistics: Bayes PPV/NPV, exact intervals, ROC/PR, calibration, strict-FPR operating points, reference watermark, nine experiments. No I/O. |
| Analysis methods | `ml/aegis_ml` | Content sniffing, extraction, every forensic/detection/verification method, provider adapters, evidence fusion policy. No database. |
| Application | `apps/api/app` | Identity, RBAC, tenancy, cases, evidence vault, job orchestration, reports, audit, benchmarks, administration. |
| Presentation | `apps/web` | Investigative workstation; talks only to the versioned REST API. |

## Components

```mermaid
flowchart LR
  subgraph Browser
    W[Next.js workstation<br/>in-memory access token]
  end
  subgraph Edge
    RP[TLS reverse proxy<br/>(operator-provided)]
  end
  subgraph App["Application tier"]
    WEB[web :3000<br/>Next.js server, /api rewrite]
    API[api :8000<br/>FastAPI + SQLAlchemy]
    WK[worker ×N<br/>Celery]
    BT[beat<br/>stale-job recovery]
  end
  subgraph Data["Data tier"]
    PG[(PostgreSQL 16<br/>cases, runs, audit chain)]
    RD[(Redis 7<br/>broker, rate limits, heartbeat)]
    OS[(Evidence store<br/>write-once local FS or S3)]
  end
  EXT[[Optional external detectors<br/>blocked by default]]
  W --> RP --> WEB --> API
  API --> PG
  API --> RD
  API --> OS
  RD --> WK
  WK --> PG
  WK --> OS
  BT --> RD
  WK -. only if deployment, org and case allow .-> EXT
```

## Evidence and analysis data flow

```mermaid
sequenceDiagram
  participant U as Investigator
  participant A as API
  participant S as Evidence store
  participant Q as Redis queue
  participant K as Worker
  participant D as PostgreSQL
  U->>A: POST /investigations/{id}/evidence (multipart or chunked)
  A->>A: stream to temp file, size limit, SHA-256
  A->>A: content sniff → structural parse → malware scan (if configured)
  A->>S: write-once original (content-addressed)
  A->>S: derived versions (normalised text / thumbnail)
  A->>D: EvidenceItem, EvidenceVersion, FileHash, AuditEvent (chained)
  U->>A: POST /analysis/investigations/{id}/jobs (profile)
  A->>D: AnalysisJob + DetectorRun rows (pending)
  A->>Q: run_analysis_job(job_id)
  Q->>K: deliver (late ack)
  loop each method
    K->>D: run → running (persisted)
    K->>K: method.run() → completed | unavailable | failed | insufficient | blocked
    K->>S: artefacts (spectra, spectrograms, contact sheets)
    K->>D: outputs, segments, AnalysisSignal, ProvenanceRecord
  end
  K->>D: fusion (aegis-fusion-v1), status, audit, notifications
  U-->>A: GET /analysis/jobs/{id}/events (SSE of persisted state)
```

## Investigation state machine

```mermaid
stateDiagram-v2
  [*] --> draft
  draft --> evidence_acquired: first evidence (automatic)
  evidence_acquired --> analysis_queued: job created (automatic)
  analysis_queued --> analysis_complete: all jobs terminal (automatic)
  analysis_complete --> analysis_queued: more analysis
  analysis_complete --> human_review: request review (reviewer assigned)
  human_review --> analysis_queued: reviewer requests further analysis
  human_review --> inconclusive: reviewer decision
  human_review --> report_finalized: report finalised (needs review decision, different person)
  inconclusive --> report_finalized
  report_finalized --> archived
  report_finalized --> human_review: reopen (case.reopen + reason)
  inconclusive --> human_review: reopen
  archived --> human_review: reopen
```

Finalised and archived cases refuse edits and new evidence. Corrections create a new report version and preserve the previous one.

## Key design properties

- **No fabricated output.** `AnalysisMethod.run()` wraps every method. Unsupported input, a policy block, missing configuration or an exception each produce an explicit status. A score is only ever set by a method that actually computed it.
- **Idempotent, resumable jobs.** `DetectorRun` is unique per `(job_id, method_id)`. A redelivered task skips completed runs. `recover_stale` requeues jobs abandoned by a lost worker, at most three attempts.
- **Truthful progress.** Progress is `methods_done / methods_total` from the database. SSE emits only when persisted state changes; nothing is timer-driven.
- **Evidence classes never mix.** The fusion policy (`ml/aegis_ml/fusion.py`) never averages or multiplies scores. It reports agreeing, conflicting, missing and failed signals, and a contradiction state.
- **Separation of duties.** The case creator cannot review their own case. A report's author cannot finalise it. A deletion requester cannot approve their own request. An appellant cannot resolve their own appeal.
- **Defence in depth on tenancy.** Every query is scoped by organisation membership. Identifiers belonging to another tenant return 404, identical to "missing".
- **Reproducible reports.** The PDF is rendered from the canonical JSON payload in ReportLab invariant mode, so verification re-renders it and compares hashes.

## Scaling notes

The API is stateless; run multiple uvicorn workers or replicas behind the proxy. Workers scale horizontally. Model-backed methods should run in dedicated worker pools (separate queue) sized to model memory, with GPU nodes where available. PostgreSQL holds only structured data; binaries live in object storage. The exception is the `database` storage backend, for hosts without a persistent disk (see [Render](../operations/render.md)), which keeps write-once objects in PostgreSQL and suits small deployments only. See [performance](../operations/performance.md) for measured numbers and test conditions.
