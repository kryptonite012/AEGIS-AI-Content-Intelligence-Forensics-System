# syntax=docker/dockerfile:1.7
# AEGIS web workstation. Build from the repository root:
#   docker build -f infrastructure/docker/web.Dockerfile -t aegis-web .
# Behind a TLS-inspecting proxy: --secret id=extra_ca,src=/path/to/proxy-ca.pem (build-time only).
FROM node:22-bookworm-slim AS deps
ENV NEXT_TELEMETRY_DISABLED=1 NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca
RUN --mount=type=secret,id=extra_ca npm install -g pnpm@10.28.0
WORKDIR /repo
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
RUN --mount=type=secret,id=extra_ca pnpm install --frozen-lockfile --filter @aegis/web...

FROM deps AS build
# Rewrites (/api/* -> API) are resolved at build time by Next.js.
ARG AEGIS_API_INTERNAL_URL=http://api:8000
ENV AEGIS_API_INTERNAL_URL=$AEGIS_API_INTERNAL_URL
COPY packages packages
COPY apps/web apps/web
RUN pnpm --filter @aegis/web build

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN groupadd --system --gid 10001 aegis && useradd --system --uid 10001 --gid aegis aegis
COPY --from=build --chown=aegis:aegis /repo/apps/web/.next/standalone ./
COPY --from=build --chown=aegis:aegis /repo/apps/web/.next/static ./apps/web/.next/static
USER aegis
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
