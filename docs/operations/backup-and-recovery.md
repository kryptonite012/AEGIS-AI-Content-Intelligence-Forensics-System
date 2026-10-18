# Backup and recovery

AEGIS state lives in three places. Back up all three together, so that hashes, audit events and objects stay consistent:

| Store | What | Method |
| --- | --- | --- |
| PostgreSQL | cases, hashes, runs, reports metadata, audit chain | `pg_dump -Fc` nightly plus WAL archiving or managed point-in-time recovery |
| Evidence store | originals, derivatives, artefacts, report PDFs, datasets | Filesystem snapshot or `rsync` of `AEGIS_STORAGE_ROOT`; on S3, bucket versioning with Object Lock plus cross-region replication |
| Configuration | `.env` / secret-manager entries, trust anchors, model directories | Secret-manager backup; record checksums of model weights |

Redis holds only queue messages, rate-limit counters and the worker heartbeat. Losing it re-queues nothing by itself; run `python -m app.cli recover-jobs` afterwards.

## Example (Compose)

```bash
docker compose exec -T postgres pg_dump -U aegis -Fc aegis > backup/aegis-$(date +%F).dump
docker run --rm -v aegis_evidence:/src -v "$PWD/backup":/dst alpine tar czf /dst/evidence-$(date +%F).tgz -C /src .
docker compose exec api python -m app.cli verify-audit > backup/audit-head-$(date +%F).json   # also anchors the head
```

## Restore test (do this quarterly, and record the result)

1. Restore the dump into an empty database: `pg_restore -d aegis_restore backup/aegis-YYYY-MM-DD.dump`.
2. Restore the evidence archive to an empty volume.
3. Start an isolated stack against the restored data with `AEGIS_DATABASE_URL` and `AEGIS_STORAGE_ROOT` pointing at the restored copies.
4. Run `python -m app.cli verify-audit`. It must report `valid: true`, and its head must match the anchored value.
5. Run `python -m app.cli verify-evidence`. Every item must report `OK`; any `MISMATCH` means the backup is inconsistent.
6. Open a case in the UI and run report verification on a finalised report. It must report intact and reproducible.

**Status in this repository:** the procedure is documented, and the verification commands exist and are tested. A restore test against real backups has **not** been run here and must be run by the operator.
