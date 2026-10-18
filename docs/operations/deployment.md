# Deployment

## Prerequisites

Docker 24+ with Compose v2 (containerised), or Python 3.11+, uv, Node 22, pnpm 10, PostgreSQL 16, Redis 7 and ffmpeg (bare metal). For any shared use you also need a TLS-terminating reverse proxy, such as nginx, Caddy or an institutional load balancer.

## Containerised deployment (pilot)

```bash
cp .env.example .env
# Required changes:
#   AEGIS_SECRET_KEY      64+ random characters   python -c "import secrets;print(secrets.token_urlsafe(64))"
#   POSTGRES_PASSWORD     strong password
#   AEGIS_ENVIRONMENT     production   (refuses dev secret key, inline tasks, insecure cookies)
#   AEGIS_MODE            research | connected-production
#   AEGIS_COOKIE_SECURE   true
#   AEGIS_CORS_ORIGINS    https://aegis.example.org
#   AEGIS_REFERENCE_WATERMARK_KEY   new secret, or leave empty to disable the verifier
docker compose build
docker compose up -d                     # migrate runs first; api/worker/beat/web start after
docker compose exec api python -m app.cli create-admin \
  --email admin@example.org --name "AEGIS Administrator" --org-name "Forensics Lab" --org-slug forensics-lab
```

Optional profiles:

- `--profile s3` runs MinIO. Set `AEGIS_STORAGE_BACKEND=s3`, `AEGIS_S3_ENDPOINT_URL=http://minio:9000`, credentials and the bucket, and create the bucket with object lock if required.
- `--profile scan` runs ClamAV. Set `AEGIS_CLAMAV_HOST=clamav` and `AEGIS_REQUIRE_MALWARE_SCAN=true`.

Behind a TLS-inspecting corporate proxy, pass its CA as a build-only secret; it is not stored in the images:

```bash
DOCKER_BUILDKIT=1 docker build --secret id=extra_ca,src=/etc/ssl/proxy-ca.pem -f infrastructure/docker/api.Dockerfile -t aegis-api .
```

## Reverse proxy (example: nginx)

```nginx
server {
  listen 443 ssl http2;
  server_name aegis.example.org;
  client_max_body_size 520m;            # >= AEGIS_MAX_UPLOAD_MB
  location /api/ { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host;
                   proxy_set_header X-Forwarded-Proto https; proxy_buffering off;  # SSE
                   proxy_read_timeout 3600s; }
  location /      { proxy_pass http://127.0.0.1:3000; proxy_set_header Host $host; }
}
```

## Production checklist

- [ ] `AEGIS_ENVIRONMENT=production`; the API refuses to start with unsafe settings.
- [ ] TLS everywhere; `AEGIS_COOKIE_SECURE=true`; HSTS at the proxy.
- [ ] Secrets injected from a secret manager, not committed `.env` files.
- [ ] Disk encryption for the PostgreSQL and evidence volumes, or an S3 bucket with SSE and Object Lock.
- [ ] ClamAV enabled and `AEGIS_REQUIRE_MALWARE_SCAN=true`.
- [ ] External processing left off unless contracts and a data-processing assessment exist.
- [ ] Backups scheduled and a restore test executed ([backup-and-recovery.md](backup-and-recovery.md)).
- [ ] Audit-chain head anchored daily ([audit-chain.md](../security/audit-chain.md)).
- [ ] Demo seeding never run (it is refused in production).
- [ ] Legal, privacy and security review completed ([governance package](../governance/README.md)).

## Rollback

Images are tagged with `AEGIS_VERSION`. To roll back:

1. Stop `api`, `worker`, `beat` and `web`.
2. Restore the database snapshot taken before the upgrade, if a migration ran.
3. Start the previous tag.

Migrations are forward-only in production. Use `alembic downgrade` only on restored copies to test.
