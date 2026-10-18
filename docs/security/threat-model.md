# Threat model

Scope: an AEGIS deployment of web, API, workers, PostgreSQL, Redis and evidence storage, operated by one institution for one or more organisations (tenants). Method: STRIDE-style enumeration per asset. **Status** reflects what this repository implements; residual risk is stated honestly.

## Assets

Evidence originals and derivatives · case records and reviewer conclusions · reports · audit trail · credentials and sessions · watermark keys and provider tokens · model weights and calibration profiles · evaluation datasets.

## Trust boundaries

Browser ↔ reverse proxy ↔ web/API · API ↔ PostgreSQL/Redis/storage · worker ↔ uploaded content (untrusted parsers) · worker ↔ external providers (optional) · operators/administrators (privileged).

## Threats and controls

| # | Threat | Controls in AEGIS | Residual risk / operator action |
| --- | --- | --- | --- |
| T1 | **Malicious uploads** (exploits in parsers, polyglots, executables) | Bytes-only type detection; executables and macro documents rejected; structural parse before acceptance; ffmpeg/ffprobe run without a shell and with timeouts; Pillow decompression-bomb limit; optional ClamAV with `AEGIS_REQUIRE_MALWARE_SCAN`; content is never executed | Parser vulnerabilities (Pillow, pypdf, ffmpeg) remain possible. Keep dependencies patched (`make security-check`); run workers with minimal privileges and no outbound network where possible. |
| T2 | **Archive attacks** (zip bombs, path traversal) | DOCX accepted only with OOXML structure; entry count, uncompressed size, compression ratio, encryption and path checks; other ZIPs rejected | — |
| T3 | **Denial of service through oversized media** | Upload size limits (global and text-specific), chunk-size limits, media duration limits, analysis caps (sampled frames, first 900 s of audio, 16 text chunks), per-user upload and API rate limits, worker time limits | Large-scale DDoS protection belongs at the edge (proxy/WAF). |
| T4 | **Unauthorized evidence access** | Server-side RBAC on every endpoint; download needs `evidence.download` and is audited; restricted classification; opaque storage keys never exposed; downloads served as `application/octet-stream` attachments | — |
| T5 | **Cross-tenant data leakage** | Every query scoped by membership; other tenants' IDs return 404; organisation header validated against memberships; tested | Shared infrastructure (one database). Separate deployments are needed for strict physical isolation. |
| T6 | **Privileged-user abuse** | Separation of duties (creator ≠ reviewer, author ≠ finaliser, requester ≠ deletion approver); every administrative change audited with a reason; org admins cannot record review decisions | A DBA can alter the database directly. Hash chaining detects partial edits; anchor the chain head externally (T9). |
| T7 | **Compromised provider credentials** | Tokens server-side only (env/secret store); never logged or returned; HTTPS required; external processing off by default and gated at three levels | Rotate tokens; scope provider accounts to inference only. |
| T8 | **Malicious or misleading provider responses** | Strict response validation (types, finite numbers, bounded strings, request-id format); vendor probabilities stored as vendor-reported, never as AEGIS calibration; non-200 → `failed` | A provider can still return plausible but wrong scores. Benchmark providers locally before relying on them. |
| T9 | **Tampering with reports or the audit trail** | Reports: canonical JSON hash, PDF hash, deterministic re-render check, immutable finals, corrections as new versions. Audit: hash chain with `/audit/verify`; tests prove detection | Whole-chain rewrite by a privileged actor; mitigate by periodically recording `/audit/head` in a separately controlled system (ticketing, WORM storage, timestamping service). |
| T10 | **Prompt injection through untrusted documents** | No LLM agent processes documents. Extracted text is data only; instruction-like phrases are recorded as an extraction warning and have no effect | If an LLM-based method is added later, it must not be given tools or policy authority. |
| T11 | **Model supply-chain risks** (poisoned or swapped weights) | Weights loaded only from operator-configured local paths with `local_files_only`; model identity and partial weight fingerprint recorded per run; registry records licence and validation | Verify weight checksums against the publisher; record them in the registry before enabling. |
| T12 | **Compromised background worker** | Workers hold only database/storage credentials; artefacts content-addressed; job state transitions audited | Run workers in a separate network segment with no inbound access; use least-privilege database roles in production. |
| T13 | **Session theft / CSRF** | 15-minute access tokens in memory; refresh rotation; httpOnly SameSite=Strict cookie scoped to the auth path; custom-header CSRF check on refresh; session revocation on logout, password change and deactivation; CSP and frame denial | Enable `AEGIS_COOKIE_SECURE` and HTTPS in production. |
| T14 | **Credential stuffing / brute force** | Argon2id; per-IP+email rate limit; lockout after 10 failures; optional TOTP | Integrate an institutional IdP with MFA enforcement (roadmap). |
| T15 | **Injection** (SQL, header, path) | SQLAlchemy parameterisation; filenames sanitised; storage keys validated against traversal; tests include SQL meta-characters | — |
| T16 | **Misuse of findings** (treating a flag as proof) | Outcome categories describe evidence; standard limitations in every report; review decision required before finalisation; UI copy and banners | Organisational policy and training remain essential. |
| T17 | **Sensitive data exposure in logs/errors** | Generic 500 messages with correlation IDs; structured logs redact secret-like keys; sensitive EXIF fields (GPS, serials) redacted in views | Configure log retention and access at the platform level. |

## Out of scope (by design)

Covert surveillance, account access, device monitoring, biometric identification, speaker or face recognition, and any inference of personal attributes. None of these exists in the codebase.
