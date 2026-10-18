# Incident response plan (template)

Adapt this plan to your institution's incident process and contacts.

| Severity | Examples | Response target |
| --- | --- | --- |
| Critical | Evidence integrity alert; audit chain verification failure; suspected cross-tenant access; credential or watermark key compromise | Immediate escalation; contain within 1 hour |
| High | Malware detected on upload; repeated authorisation failures from one account; provider sending anomalous responses | Same working day |
| Medium | Worker outage; storage nearly full; dependency advisory affecting a deployed component | 2 working days |

## Playbooks

**Integrity alert** (`evidence.integrity_mismatch`):
1. Do not re-run analyses or export reports for the affected item.
2. Preserve the storage object, the database rows and the logs as they are.
3. Compare against backups to establish when the change happened.
4. Check access logs and the audit trail around that time.
5. Notify the case owner and the reviewer; record findings as annotations.

**Audit chain broken** (`/audit/verify` returns `valid: false`):
1. Snapshot the database.
2. Compare the chain with the anchored heads to locate the alteration window.
3. Treat it as a privileged-access incident.

**Credential compromise**:
1. Deactivate the account, which revokes its sessions.
2. Rotate `AEGIS_SECRET_KEY` (this invalidates every access token and MFA encryption, so users re-enrol MFA), provider tokens and the reference watermark key.
3. Review the audit trail for the account.

**Provider anomaly**: disable the method in the model registry (audited), then investigate. Disabled methods are recorded as unavailable in later runs.

After every incident, run a post-incident review: timeline, root cause, corrective actions, and any changes needed to the compliance mapping.
