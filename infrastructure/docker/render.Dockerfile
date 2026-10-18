# syntax=docker/dockerfile:1.7
# AEGIS in one container, for platforms that run a single web process per service (for example the
# Render free plan; see docs/operations/render.md). The web workstation listens on $PORT and forwards
# /api/* to the API on 127.0.0.1:8000. Build from the repository root:
#   docker build -f infrastructure/docker/render.Dockerfile -t aegis-render .
# Behind a TLS-inspecting proxy: --secret id=extra_ca,src=/path/to/proxy-ca.pem (build-time only).
FROM mwader/static-ffmpeg:7.1 AS ffmpeg

FROM node:22-bookworm-slim AS web
ENV NEXT_TELEMETRY_DISABLED=1 NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca
RUN --mount=type=secret,id=extra_ca npm install -g pnpm@10.28.0
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
RUN --mount=type=secret,id=extra_ca pnpm install --frozen-lockfile --filter @aegis/web...
# Rewrites (/api/* -> API) are resolved at build time by Next.js.
ENV AEGIS_API_INTERNAL_URL=http://127.0.0.1:8000
COPY packages packages
COPY apps/web apps/web
RUN pnpm --filter @aegis/web build

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
COPY --from=web /usr/local/bin/node /usr/local/bin/node
RUN printf '#!/bin/sh\nset -e\nB=/etc/ssl/certs/ca-certificates.crt\nif [ -s /run/secrets/extra_ca ]; then cat "$B" /run/secrets/extra_ca > /tmp/ca.pem; B=/tmp/ca.pem; fi\nSSL_CERT_FILE=$B PIP_CERT=$B "$@"\nrm -f /tmp/ca.pem\n' > /usr/local/bin/with-ca \
 && chmod +x /usr/local/bin/with-ca \
 && groupadd --system --gid 10001 aegis \
 && useradd --system --uid 10001 --gid aegis --home /app --shell /usr/sbin/nologin aegis
RUN --mount=type=secret,id=extra_ca with-ca pip install --no-cache-dir uv==0.5.11

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY ml/pyproject.toml ml/pyproject.toml
COPY research/pyproject.toml research/pyproject.toml
RUN --mount=type=secret,id=extra_ca mkdir -p apps/api/app ml/aegis_ml research/aegis_research \
 && with-ca uv sync --frozen --no-dev --no-install-workspace --package aegis-api

COPY research research
COPY ml ml
COPY apps/api apps/api
COPY docs/governance docs/governance
RUN --mount=type=secret,id=extra_ca with-ca uv sync --frozen --no-dev --package aegis-api \
 && mkdir -p /var/lib/aegis/evidence \
 && chown -R aegis:aegis /var/lib/aegis

COPY --from=web --chown=aegis:aegis /repo/apps/web/.next/standalone /app/web
COPY --from=web --chown=aegis:aegis /repo/apps/web/.next/static /app/web/apps/web/.next/static
COPY infrastructure/render/serve.py /app/infrastructure/render/serve.py
COPY --chmod=755 infrastructure/render/start.sh /usr/local/bin/aegis-start

USER aegis
WORKDIR /app/apps/api
ENV AEGIS_STORAGE_ROOT=/var/lib/aegis/evidence PORT=10000
EXPOSE 10000
CMD ["aegis-start"]
