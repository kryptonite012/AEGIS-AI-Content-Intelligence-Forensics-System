"""AEGIS API entrypoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import analysis, auth, evidence, investigations, platform, reports, research
from app.core import errors
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware

DESCRIPTION = """
AEGIS — Advanced Evidence, Generation Intelligence & Synthetic-Media Forensics System.

Defensive forensic API for authorised analysts. Statistical inference, watermark verification,
signed provenance, media-forensic observations, process evidence and human assessment are distinct
evidence classes and are never presented as interchangeable. No endpoint returns fabricated results:
methods that cannot run report `unavailable`.

Authentication: `Authorization: Bearer <access token>` from `POST /api/v1/auth/login`. Select an
organisation with the `X-AEGIS-Organization` header when a user belongs to several.
Errors: `{"error": {"code", "message", "correlation_id", "details"}}`; every response carries `X-Request-ID`.
"""


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    s = get_settings()
    if s.task_mode == "inline" and s.resume_inline_jobs_on_startup:
        from app.db import get_sessionmaker
        from app.services.analysis import resume_inline_jobs

        with get_sessionmaker()() as db:
            n = resume_inline_jobs(db)
        if n:
            logging.getLogger("aegis").info("resumed %d interrupted job(s)", n)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging()
    problems = s.check_production_safety()
    if problems:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))
    app = FastAPI(
        title="AEGIS API",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Requested-With",
            "X-AEGIS-Organization",
            "Idempotency-Key",
            "X-Request-ID",
        ],
        expose_headers=["X-Request-ID", "X-AEGIS-SHA256"],
    )
    errors.install(app)
    for r in (
        auth.router,
        investigations.router,
        evidence.router,
        analysis.router,
        reports.router,
        research.router,
        platform.router,
    ):
        app.include_router(r, prefix="/api/v1")
    logging.getLogger("aegis").info("AEGIS API started", extra={"ctx_mode": str(s.mode)})
    return app


app = create_app()
