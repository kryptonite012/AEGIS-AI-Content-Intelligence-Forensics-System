# Performance

All numbers below were **measured** with `scripts/loadtest.py` (`make loadtest`). They describe only the conditions listed here and are not a capacity claim for any production deployment.

## Test conditions

| Item | Value |
| --- | --- |
| Host | Cloud development container, 4 vCPU, 15 GiB RAM, Linux 6.18, single host for every component |
| Services | PostgreSQL 16 and Redis 7 (local), uvicorn with 2 workers, Celery worker with concurrency 2, local filesystem storage |
| Software | Python 3.13, FastAPI 0.143, SQLAlchemy 2.0, Celery 5.6 |
| Data | Demo seed plus earlier test data (about 10 cases) |
| Rate limits | Raised for the test (`AEGIS_API_RATE_LIMIT_PER_MINUTE=100000`). The default of 600/min per user would throttle a single-user load test. |
| Command | `python scripts/loadtest.py --concurrency 8 --requests 400 --jobs 20` |
| Date | 2026-10-18 |

## Results

| Phase | Requests | Errors | Throughput | p50 | p95 | p99 |
| --- | --- | --- | --- | --- | --- | --- |
| Read (`GET /investigations`, `GET /overview`), 8 concurrent | 400 | 0 | 139 req/s | 51 ms | 98 ms | 145 ms |
| PPV calculator, 8 concurrent | 400 | 0 | 265 req/s | 28 ms | 48 ms | 52 ms |
| Text evidence upload (about 3 KB, sequential) | 20 | 0 | 18.6 req/s | 45 ms | 52 ms | 273 ms |

| Jobs | Value |
| --- | --- |
| 20 `text_triage` jobs queued together | 20/20 completed, none timed out |
| Wall time | 2.17 s (≈ 553 jobs/min) |
| Completion latency | p50 1.46 s, max 1.92 s |

**Interpretation.** `text_triage` jobs are cheap in this build because the four model-backed text methods are unavailable; the measured work is extraction-dependent statistics and the watermark z-test. Jobs with transformer detectors will be dominated by model inference and need dedicated, possibly GPU-backed, worker pools. Image and video jobs depend on resolution and duration. For the demo-seed 4-second 320×240 video, the recorded run durations on this host were 49 ms (`video.container`) and 386 ms (`video.temporal_consistency`, 2 fps sampling). Re-measure on your own hardware before planning capacity.

## Built-in limits that bound resource use

Upload size 512 MB (text/documents 25 MB). Chunk size 8 MB. Audio up to 3 h accepted, first 900 s analysed. Video up to 2 h accepted, at most 240 sampled frames. Images are analysed downsampled to 1024 px. Text extraction is capped at 2 M characters; classifier scoring at 16 × 512 tokens. Celery hard time limit is 3,600 s per job.
