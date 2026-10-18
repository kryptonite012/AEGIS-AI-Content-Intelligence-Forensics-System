#!/bin/bash
# Entry point of infrastructure/docker/render.Dockerfile. Starts the API on 127.0.0.1:8000 (serve.py:
# migrations, demo data, API), then the web workstation on $PORT, so the public port opens only once
# the API can answer.
# If either process stops, the container exits and the platform restarts it.
set -euo pipefail
cd /app/apps/api

# No Redis unless one is configured: jobs run in process, rate limits are kept in memory.
export AEGIS_REDIS_URL="${AEGIS_REDIS_URL:-}"
# Render publishes the service's public URL; the browser only ever talks to that origin.
if [ -z "${AEGIS_CORS_ORIGINS:-}" ] && [ -n "${RENDER_EXTERNAL_URL:-}" ]; then
  export AEGIS_CORS_ORIGINS="$RENDER_EXTERNAL_URL"
fi

# uvicorn opens its port only after the startup hook (job resumption) has finished.
api_listening() { (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null; }

python /app/infrastructure/render/serve.py &
api=$!
pids=("$api")
trap 'kill -TERM "${pids[@]}" 2>/dev/null || true' TERM INT
until api_listening; do
  kill -0 "$api" 2>/dev/null || { wait "$api"; exit 1; }
  sleep 1
done

HOSTNAME=0.0.0.0 PORT="${PORT:-10000}" node --max-old-space-size=160 /app/web/apps/web/server.js &
web=$!
pids+=("$web")

status=0
wait -n "$api" "$web" || status=$?
kill -TERM "${pids[@]}" 2>/dev/null || true
wait || true
exit "$status"
