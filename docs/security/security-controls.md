# Security controls matrix

The machine-readable version, including status per control, is [`docs/governance/compliance-mapping.json`](../governance/compliance-mapping.json); the UI shows it under Audit & Compliance.

| Control | Implementation | Verified by |
| --- | --- | --- |
| Authentication | Argon2id (`argon2-cffi`), JWT HS256 access tokens (15 min) bound to `user_sessions`, rotating refresh tokens (SHA-256 stored), optional TOTP | `test_session_revocation`, `test_refresh_requires_csrf_header`, `test_login_rate_limit_and_lockout` |
| Authorisation | `require(*permissions)` dependency on every route; 32 permissions across 7 roles in `security/permissions.py` | `test_role_permissions_enforced_server_side` |
| Tenant isolation | `visible_cases()` scoping; 404 for foreign IDs; membership-checked organisation header | `test_cross_tenant_isolation`, `test_restricted_classification` |
| Separation of duties | Creator ≠ reviewer; author ≠ finaliser; requester ≠ approver; appellant ≠ resolver; org admin cannot decide reviews | `test_full_text_workflow`, `test_state_machine_rules`, `test_requester_cannot_approve_own_deletion`, `test_appeal_workflow` |
| Input validation | Pydantic schemas, size/length limits, content sniffing, structural parsing | `test_malicious_uploads_rejected`, `test_zip_traversal_and_bomb_rejected`, `test_oversized_upload`, `test_filename_is_sanitised` |
| Rate limiting | Redis fixed window (in-process fallback): login, uploads, per-user API | `test_login_rate_limit_and_lockout` |
| Security headers | CSP (`default-src 'none'` on API), nosniff, DENY framing, no-referrer, HSTS over HTTPS, `Cache-Control: no-store` | `test_error_format_and_headers` |
| CORS | Explicit origin allow-list (`AEGIS_CORS_ORIGINS`) | configuration |
| Secrets | Environment / secret store only; never in responses, logs or reports; production refuses dev secret key, inline tasks and insecure cookies | `test_no_secrets_in_responses`, `Settings.check_production_safety` |
| Evidence integrity | SHA-256 at acquisition; write-once storage; re-verification with critical alerts | `test_integrity_verification_and_mismatch_alert`, `test_storage_is_write_once` |
| Audit | Append-only hash chain, verification endpoint, head export | `test_audit_tampering_detected` |
| Report integrity | Canonical JSON hash, PDF hash, deterministic re-render | `test_report_tampering_detected` |
| External processing | Off by default; deployment AND organisation AND case must allow it | `test_provider_failure_and_policy` |
| Dependency hygiene | Locked dependencies; `make security-check` (pip-audit, pnpm audit, CycloneDX SBOM) | Clean at the time of this release (see `docs/governance/sbom/`) |
| Encryption in transit | Operator TLS proxy; `AEGIS_COOKIE_SECURE=true` | deployment guide |
| Encryption at rest | S3 SSE requested; MFA secrets Fernet-encrypted; disk encryption for local storage and PostgreSQL is the operator's responsibility | partial |
| Backups | Procedure and restore test in `docs/operations/backup-and-recovery.md` | must be executed by the operator |
