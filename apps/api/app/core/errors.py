"""Consistent error responses: {"error": {"code", "message", "correlation_id", "details"}}."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("aegis.errors")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str = "resource") -> AppError:
    # Same response for "missing" and "not yours" so identifiers cannot be probed across tenants.
    return AppError(404, "not_found", f"{what} not found")


def forbidden(message: str = "You do not have permission to perform this action.") -> AppError:
    return AppError(403, "forbidden", message)


def conflict(message: str, details: Any = None) -> AppError:
    return AppError(409, "conflict", message, details)


def bad_request(message: str, code: str = "bad_request", details: Any = None) -> AppError:
    return AppError(400, code, message, details)


def _body(request: Request, code: str, message: str, details: Any = None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "correlation_id": getattr(request.state, "correlation_id", None),
            "details": details,
        }
    }


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError):  # type: ignore[no-untyped-def]
        return JSONResponse(_body(request, exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):  # type: ignore[no-untyped-def]
        code = {
            401: "unauthenticated",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            413: "payload_too_large",
            429: "rate_limited",
        }.get(exc.status_code, "http_error")
        return JSONResponse(
            _body(request, code, str(exc.detail)), status_code=exc.status_code, headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError):  # type: ignore[no-untyped-def]
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
        return JSONResponse(_body(request, "validation_error", "Request validation failed.", details), status_code=422)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # type: ignore[no-untyped-def]
        log.exception("unhandled error", extra={"correlation_id": getattr(request.state, "correlation_id", None)})
        return JSONResponse(_body(request, "internal_error", "An internal error occurred."), status_code=500)
