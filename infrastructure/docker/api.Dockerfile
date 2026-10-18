# syntax=docker/dockerfile:1.7
# AEGIS API and worker image (same image, different command).
# Build from the repository root:  docker build -f infrastructure/docker/api.Dockerfile -t aegis-api .
# Behind a TLS-inspecting proxy, pass its CA for the build only (it is not kept in the image):
#   docker build --secret id=extra_ca,src=/path/to/proxy-ca.pem ...
FROM mwader/static-ffmpeg:7.1 AS ffmpeg

FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

# Static, pinned ffmpeg/ffprobe builds (no distribution package mirror needed).
COPY --from=ffmpeg /ffmpeg /ffprobe /usr/local/bin/
# Runs a command with the optional build-time CA appended to the system bundle (temporary file only).
RUN printf '#!/bin/sh\nset -e\nB=/etc/ssl/certs/ca-certificates.crt\nif [ -s /run/secrets/extra_ca ]; then cat "$B" /run/secrets/extra_ca > /tmp/ca.pem; B=/tmp/ca.pem; fi\nSSL_CERT_FILE=$B PIP_CERT=$B "$@"\nrm -f /tmp/ca.pem\n' > /usr/local/bin/with-ca \
 && chmod +x /usr/local/bin/with-ca \
 && groupadd --system --gid 10001 aegis \
 && useradd --system --uid 10001 --gid aegis --home /app --shell /usr/sbin/nologin aegis
RUN --mount=type=secret,id=extra_ca with-ca pip install --no-cache-dir uv==0.5.11

WORKDIR /app
# Dependency layer: only lock and project metadata.
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
 && mkdir -p /var/lib/aegis/evidence /var/lib/aegis/tmp \
 && chown -R aegis:aegis /var/lib/aegis

USER aegis
WORKDIR /app/apps/api
ENV AEGIS_STORAGE_ROOT=/var/lib/aegis/evidence
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*", "--workers", "2"]
