# Architecture decisions

Short records of the choices that shape the system. The newest decisions are at the end.

**ADR-01: Python services, TypeScript workstation.** Detection research and forensic tooling (NumPy/SciPy, Pillow, ffmpeg, c2pa-rs bindings, PyTorch/ONNX) live in Python. The analyst UI is Next.js with typed API contracts in `packages/shared-types`.

**ADR-02: Methods are libraries, not services.** Analysis methods live in `aegis_ml` and run inside workers. This keeps one versioned code path for API, worker, CLI and benchmarks. External services connect through `HttpDetectorProvider` with a strict JSON contract.

**ADR-03: Explicit capability status instead of fallbacks.** No method substitutes a heuristic when a model is missing. Unconfigured methods are `unavailable`, and the UI shows the reason. This rules out silent fake scores.

**ADR-04: Fusion by evidence class, not by score arithmetic.** No detector pair has held-out joint validation and detector dependence is unknown, so `aegis-fusion-v1` combines only categorical facts (flagged under a validated threshold, verified, failed). It reports contradictions instead of resolving them. A learned combiner may be added only with documented held-out validation.

**ADR-05: Raw scores are not probabilities.** `flagged` and `calibrated` are set only when a calibration profile validated on locally measured data is attached through the model registry, or ships beside the model (`aegis_calibration.json` with `validated: true`).

**ADR-06: Content-addressed, write-once evidence storage.** Keys derive from SHA-256. Writes use temp-file plus hard link to prevent overwrite races, and objects are made read-only. Deletion is possible only through the audited, two-person retention purge, which keeps tombstones.

**ADR-07: Hash-chained audit trail in the primary database.** This is simple and transactional with the operation it records (an event commits or rolls back with it). It is tamper-evident but not tamper-proof against a privileged DBA; head anchoring is the documented mitigation.

**ADR-08: Celery + Redis with database-persisted job state.** The broker carries only job ids. All state lives in PostgreSQL, so refreshes, worker loss and redelivery are safe. Late acknowledgement and per-run uniqueness make execution idempotent.

**ADR-09: Access token in memory, refresh token in an httpOnly SameSite=Strict cookie scoped to `/api/v1/auth`.** The refresh endpoint also requires a custom header, which cross-site forms cannot send. The browser talks to the API through a same-origin rewrite.

**ADR-10: Reference watermark as a real, narrow verifier.** No provider watermark verifier was available. AEGIS implements the published green-list scheme with its own keyed generator, so the verification pathway (keys, exact p-values, length checks, robustness benchmarks) is exercised end to end. It is labelled everywhere as able to verify only AEGIS-generated reference text.

**ADR-11: Static ffmpeg in container images.** Images copy pinned static ffmpeg/ffprobe builds (`mwader/static-ffmpeg:7.1`). Builds then need no distribution package mirror, and the media toolchain version is pinned.

**ADR-12: Next.js 15 with React 18.** Moving to Next 15.5 cleared all `pnpm audit` advisories. React 18.3 is kept to limit churn; Next 15 supports it.
