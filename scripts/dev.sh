#!/usr/bin/env bash
# Runs the API, a Celery worker and the web app for local development.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
export NEXT_TELEMETRY_DISABLED=1
pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM
(cd apps/api && uv run --frozen uvicorn app.main:app --reload --host 127.0.0.1 --port 8000) & pids+=($!)
(cd apps/api && uv run --frozen celery -A app.workers.celery_app worker -Q aegis,aegis-research -c 2 --loglevel=INFO) & pids+=($!)
pnpm --filter @aegis/web dev & pids+=($!)
echo "AEGIS: web http://localhost:3000  ·  API docs http://localhost:8000/api/docs"
wait -n
