#!/usr/bin/env bash
# One-command AEGIS installation on a Linux server (Ubuntu/Debian/RHEL with Docker).
#   sudo ./scripts/server-setup.sh aegis.college.edu      # public DNS name -> Let's Encrypt HTTPS
#   sudo ./scripts/server-setup.sh 10.20.30.40            # campus IP / internal name -> internal-CA HTTPS
# Re-running is safe: secrets in an existing .env are kept.
set -euo pipefail
cd "$(dirname "$0")/.."

SITE="${1:-}"
if [ -z "$SITE" ]; then
  echo "usage: $0 <domain-or-ip>"; exit 1
fi
command -v docker >/dev/null || { echo "Docker is required: https://docs.docker.com/engine/install/"; exit 1; }
docker compose version >/dev/null || { echo "Docker Compose v2 is required"; exit 1; }

rand() { tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$1"; }
if [[ "$SITE" =~ ^[0-9.]+$ ]] || [[ "$SITE" != *.* ]] || [[ "$SITE" == *.local ]] || [[ "$SITE" == *.lan ]] || [[ "$SITE" == *.internal ]]; then
  TLS="tls internal"; echo "Using an internal certificate for $SITE (browsers will ask you to trust it once)."
else
  TLS=""; echo "Requesting a public Let's Encrypt certificate for $SITE (ports 80 and 443 must be reachable)."
fi

if [ ! -f .env ]; then
  cp .env.example .env
  sed -i "s#^AEGIS_SECRET_KEY=.*#AEGIS_SECRET_KEY=$(rand 64)#" .env
  sed -i "s#^AEGIS_REFERENCE_WATERMARK_KEY=.*#AEGIS_REFERENCE_WATERMARK_KEY=$(rand 40)#" .env
  sed -i "s#^AEGIS_DEMO_PASSWORD=.*#AEGIS_DEMO_PASSWORD=$(rand 20)Aa1#" .env
  echo "POSTGRES_PASSWORD=$(rand 32)" >> .env
fi
set_kv() { if grep -q "^$1=" .env; then sed -i "s#^$1=.*#$1=$2#" .env; else echo "$1=$2" >> .env; fi; }
set_kv AEGIS_SITE "$SITE"
set_kv AEGIS_TLS_DIRECTIVE "\"$TLS\""
set_kv AEGIS_ENVIRONMENT production
set_kv AEGIS_MODE research
set_kv AEGIS_COOKIE_SECURE true
set_kv AEGIS_CORS_ORIGINS "https://$SITE"
chmod 600 .env

COMPOSE="docker compose -f docker-compose.yml -f infrastructure/deployment/docker-compose.server.yml"
$COMPOSE build
$COMPOSE up -d
echo "Waiting for the API..."
for _ in $(seq 1 60); do
  $COMPOSE exec -T api python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready')" </dev/null 2>/dev/null && break
  sleep 3
done

if ! $COMPOSE exec -T api python -c "
from app.db import get_sessionmaker; from app.models import User; from sqlalchemy import select
import sys; s=get_sessionmaker()(); sys.exit(0 if s.execute(select(User).where(User.is_system_admin.is_(True))).first() else 1)" </dev/null 2>/dev/null; then
  read -rp "Administrator email: " EMAIL
  read -rp "Administrator name: " NAME
  read -rp "Organisation name (e.g. Department of Computer Science): " ORG
  SLUG=$(echo "$ORG" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//' | cut -c1-60)
  read -rsp "Administrator password (12+ chars, upper+lower case and a digit): " PASS; echo
  $COMPOSE exec -T -e AEGIS_ADMIN_PASSWORD="$PASS" api python -m app.cli create-admin \
    --email "$EMAIL" --name "$NAME" --org-name "$ORG" --org-slug "${SLUG:-aegis}" </dev/null
fi

echo
echo "AEGIS is running:  https://$SITE"
echo "Sign in with the administrator account, then add users under Administration -> Users & roles."
