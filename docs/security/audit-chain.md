# Audit chain

Every state-changing operation appends an `audit_events` row in the same database transaction as the operation itself.

```
event_hash = SHA-256( prev_hash || canonical_json({id, occurred_at, organization_id, actor_user_id,
                                                  actor_label, action, entity_type, entity_id,
                                                  investigation_id, reason, details}) )
```

- `canonical_json` uses sorted keys, no whitespace and UTF-8.
- The first event links to `0 × 64`.
- On PostgreSQL, appends are serialised with `pg_advisory_xact_lock`, so concurrent requests cannot fork the chain.
- `POST /api/v1/audit/verify` (or `make verify`) recomputes every hash and reports the first broken sequence number.
- `GET /api/v1/audit/head` returns the latest `(seq, event_hash)`.

## What it detects

- Editing any field of any event.
- Deleting or reordering events (the next event's `prev_hash` no longer matches).

## What it does not prevent

Someone with write access to the database can recompute the whole chain after an edit. Hash chaining alone cannot detect that. To detect it:

1. Record the head hash on a schedule, for example daily, in a system the database administrators do not control: an append-only ticket, WORM object storage, a signed email to a governance mailbox, or an RFC 3161 timestamping service.
2. During audits, check that every recorded head still appears in the chain at the recorded sequence number.

Reports embed the latest event hash for their case, which gives each exported report an independent anchor.

## Chain of custody

The audit trail, the per-version SHA-256 records and the write-once store together form a technical custody record. They do **not** amount to a legally certified chain of custody. Certification requires a validated operational procedure (who may acquire evidence, how originals are obtained, how devices are handled) and legal review in the relevant jurisdiction.
