"""Applies migrations, synchronises roles and the model registry, optionally loads the demo data, and
serves the API on 127.0.0.1:8000.

Everything runs in one interpreter: on a 0.1 CPU instance every extra Python start-up costs tens of
seconds and another copy of the scientific libraries in memory.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request

import uvicorn
from alembic import command
from alembic.config import Config
from app.cli import cmd_seed_demo, cmd_sync

# Documented in the README, so it is refused on a public host.
PUBLISHED_DEMO_PASSWORD = "Aegis-Demo-Only-2026"  # noqa: S105


def _seed_when_serving() -> None:
    # Start after the API's startup hook has resumed interrupted jobs, so no job is executed twice.
    while True:
        try:
            urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health/live", timeout=5)
            break
        except OSError:
            time.sleep(2)
    cmd_seed_demo(None)  # type: ignore[arg-type]
    print("Demo organisation and DEMO FIXTURE cases are ready.", flush=True)


command.upgrade(Config("alembic.ini"), "head")
cmd_sync(None)  # type: ignore[arg-type]

if os.environ.get("AEGIS_SEED_DEMO", "").lower() == "true":
    password = os.environ.get("AEGIS_DEMO_PASSWORD", "")
    if len(password) < 12 or password == PUBLISHED_DEMO_PASSWORD:
        print(
            "Demo data not loaded: set AEGIS_DEMO_PASSWORD to a private value of at least 12 characters.",
            file=sys.stderr,
            flush=True,
        )
    else:
        threading.Thread(target=_seed_when_serving, daemon=True, name="aegis-demo-seed").start()

uvicorn.run(
    "app.main:app",
    host="127.0.0.1",
    port=8000,
    proxy_headers=True,
    forwarded_allow_ips="*",
    timeout_graceful_shutdown=20,
)
