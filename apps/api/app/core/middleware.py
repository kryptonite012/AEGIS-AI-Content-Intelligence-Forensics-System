"""Correlation IDs, security headers, request logging."""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import correlation_id_var

log = logging.getLogger("aegis.http")
_CID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        incoming = request.headers.get("x-request-id", "")
        cid = incoming if _CID.match(incoming) else str(uuid.uuid4())
        request.state.correlation_id = cid
        token = correlation_id_var.set(cid)
        started = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            correlation_id_var.reset(token)
        response.headers["X-Request-ID"] = cid
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers.setdefault("Cache-Control", "no-store")
        if request.url.path.startswith("/api/docs") or request.url.path.startswith("/api/redoc"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com"
            )
        else:
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        log.info(
            "request",
            extra={
                "correlation_id": cid,
                "ctx_method": request.method,
                "ctx_path": request.url.path,
                "ctx_status": response.status_code,
                "ctx_ms": int((time.monotonic() - started) * 1000),
            },
        )
        return response
