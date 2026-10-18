# AEGIS task runner. Run `make help` for the list of targets.
SHELL := /bin/bash
.DEFAULT_GOAL := help
PY := uv run --frozen
API := apps/api
ENV_LOAD := set -a; [ -f .env ] && . ./.env; set +a
export NEXT_TELEMETRY_DISABLED := 1

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Install Python (uv) and Node (pnpm) dependencies from lockfiles; create .env if missing
	@[ -f .env ] || (cp .env.example .env && sed -i "s#AEGIS_STORAGE_ROOT=./var/evidence#AEGIS_STORAGE_ROOT=$(CURDIR)/var/evidence#" .env && echo "created .env from .env.example")
	uv sync --frozen
	pnpm install --frozen-lockfile

services: ## Start PostgreSQL and Redis in Docker (alternative: use locally installed services)
	docker compose up -d postgres redis

migrate: ## Apply database migrations and synchronise roles/model registry
	$(ENV_LOAD); cd $(API) && $(PY) alembic upgrade head && $(PY) python -m app.cli sync

seed-demo: ## Create the demo organisation, demo users and DEMO FIXTURE cases (development only)
	$(ENV_LOAD); cd $(API) && $(PY) python -m app.cli seed-demo

dev: ## Run API (:8000), worker and web (:3000) together; Ctrl-C stops all
	./scripts/dev.sh

api: ## Run only the API with auto-reload
	$(ENV_LOAD); cd $(API) && $(PY) uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

worker: ## Run only the Celery worker
	$(ENV_LOAD); cd $(API) && $(PY) celery -A app.workers.celery_app worker -Q aegis,aegis-research -c 2 --loglevel=INFO

web: ## Run only the web app in development mode
	pnpm --filter @aegis/web dev

test: test-py test-web ## Run all unit and integration tests

test-py: ## Python tests (research, ml, API integration tests against PostgreSQL database aegis_test)
	$(PY) pytest

test-web: ## Web unit tests and type check
	pnpm --filter @aegis/web typecheck
	pnpm --filter @aegis/web test

test-e2e: ## Browser end-to-end tests against a running, seeded stack (AEGIS_WEB_URL, default http://localhost:3000)
	cd apps/web && npx playwright test

lint: ## Ruff (lint + format check) and ESLint
	$(PY) ruff check .
	$(PY) ruff format --check .
	pnpm --filter @aegis/web lint

format: ## Auto-format Python
	$(PY) ruff format .
	$(PY) ruff check --fix .

benchmark: ## Built-in simulated benchmark + the nine reliability experiments -> benchmarks/runs/
	$(ENV_LOAD); cd $(API) && $(PY) python -m app.cli benchmark --out ../../benchmarks/runs

experiments: ## Only the nine research experiments (JSON + PNG) -> research/results/
	$(PY) --with matplotlib python -m aegis_research.experiments --all --plots --out research/results

loadtest: ## Repeatable load test against a running API (see docs/operations/performance.md)
	$(PY) python scripts/loadtest.py

verify: ## Recompute every stored evidence hash and verify the audit chain
	$(ENV_LOAD); cd $(API) && $(PY) python -m app.cli verify-evidence && $(PY) python -m app.cli verify-audit

build: ## Build production container images
	docker compose build

up: ## Start the full containerised stack
	docker compose up -d

down: ## Stop the containerised stack
	docker compose down

security-check: ## Dependency vulnerability scan (pip-audit, pnpm audit) and SBOM generation
	mkdir -p var/security
	uv export --frozen --no-dev --no-hashes --no-emit-workspace -o var/security/requirements.txt
	$(PY) pip-audit -r var/security/requirements.txt --format cyclonedx-json -o var/security/sbom-python.cdx.json || true
	$(PY) pip-audit -r var/security/requirements.txt
	pnpm audit --prod
	pnpm licenses list --prod --json > var/security/node-licenses.json

clean: ## Remove build output and caches (keeps evidence and databases)
	rm -rf apps/web/.next apps/web/test-results .pytest_cache .ruff_cache

.PHONY: help setup services migrate seed-demo dev api worker web test test-py test-web test-e2e lint format benchmark experiments loadtest verify build up down security-check clean
