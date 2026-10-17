"""Structured JSON logging with correlation IDs."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

_REDACT = ("password", "token", "secret", "authorization", "api_key", "cookie")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None) or correlation_id_var.get(),
        }
        for k, v in record.__dict__.items():
            if k.startswith("ctx_"):
                payload[k[4:]] = "[redacted]" if any(r in k.lower() for r in _REDACT) else v
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel("WARNING")
