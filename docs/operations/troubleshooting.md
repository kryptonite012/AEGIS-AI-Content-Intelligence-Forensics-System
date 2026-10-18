# Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| API exits with "Unsafe production configuration" | `AEGIS_ENVIRONMENT=production` with the dev secret key, inline tasks or insecure cookies | Set a strong `AEGIS_SECRET_KEY`, use `AEGIS_TASK_MODE=celery`, set `AEGIS_COOKIE_SECURE=true` |
| `error parsing value for field "cors_origins"` | JSON list syntax in `.env` | Use a comma-separated list: `AEGIS_CORS_ORIGINS=https://a,https://b` |
| Jobs stay *queued* | No worker, or the worker is not consuming queue `aegis` | Start the worker with `-Q aegis,aegis-research`; System Health shows the worker heartbeat |
| Jobs stuck *running* after a worker crash | Lost worker | Wait for `beat` (every 10 min) or run `python -m app.cli recover-jobs` |
| Every audio/video method *unavailable* | ffmpeg/ffprobe missing on the worker | Install ffmpeg (images include static builds) |
| Text detectors *unavailable* | No model configured | Expected. See [configuring-detectors.md](configuring-detectors.md) |
| External provider *blocked by policy* | External processing is off at the deployment, organisation or case level | Expected default. All three levels must allow it. |
| Upload rejected `unsupported_media` | Content does not match a supported format (the extension is ignored), or it is an executable or a macro document | Convert to a supported format |
| Upload rejected `malformed_media` | The file fails structural parsing (corrupt or truncated) | Obtain a clean original |
| 429 `rate_limited` | Login, upload or API rate limit reached | Wait, or tune `AEGIS_*_RATE_LIMIT_*` |
| UI says "local hash unavailable" | The browser is not in a secure context (plain HTTP on a non-localhost host), or the file is over 256 MB | Serve over HTTPS. The server-side hash is recorded regardless. |
| UI redirects to sign-in repeatedly | Refresh cookie not set: HTTPS required with `AEGIS_COOKIE_SECURE=true`, or the proxy strips cookies | Serve over HTTPS, or set `AEGIS_COOKIE_SECURE=false` for local HTTP development only |
| SSE progress never updates behind nginx | Proxy buffering | `proxy_buffering off;` for `/api/` (the API also sends `X-Accel-Buffering: no`) |
| `alembic check` reports drift | Model changed without a migration | `alembic revision --autogenerate -m "..."` and review the result |
| API tests fail to connect | Test database missing | `createdb -O aegis aegis_test`, or set `AEGIS_TEST_DATABASE_URL` |
