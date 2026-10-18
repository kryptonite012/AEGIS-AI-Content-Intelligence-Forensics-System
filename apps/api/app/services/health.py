"""Truthful component health: every status comes from an actual check at request time."""

from __future__ import annotations

import shutil
import time
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AnalysisJob
from app.services.analysis import registry
from app.services.scanning import scanner_configured
from app.storage.base import get_storage


def _redis():  # type: ignore[no-untyped-def]
    import redis

    return redis.Redis.from_url(get_settings().redis_url, socket_timeout=1, socket_connect_timeout=1)


def components(db: Session) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(cid: str, name: str, group: str, ok: bool | None, detail: str) -> None:
        out.append(
            {
                "id": cid,
                "name": name,
                "group": group,
                "status": "operational" if ok else ("unknown" if ok is None else "unavailable"),
                "detail": detail,
            }
        )

    t = time.monotonic()
    try:
        db.execute(text("SELECT 1"))
        add("database", "PostgreSQL", "infrastructure", True, f"responded in {int((time.monotonic() - t) * 1000)} ms")
    except Exception as exc:  # noqa: BLE001
        add("database", "PostgreSQL", "infrastructure", False, type(exc).__name__)
    s = get_settings()
    redis_ok = False
    if not s.redis_url:
        add("redis", "Redis (queue broker)", "infrastructure", None, "not configured: rate limits are kept in process")
    else:
        try:
            r = _redis()
            r.ping()
            redis_ok = True
            add("redis", "Redis (queue broker)", "infrastructure", True, "ping ok")
        except Exception as exc:  # noqa: BLE001
            add("redis", "Redis (queue broker)", "infrastructure", False, type(exc).__name__)
    if s.task_mode == "celery":
        if redis_ok:
            hb = r.get("aegis:worker:heartbeat")
            age = time.time() - float(hb) if hb else None
            add(
                "worker",
                "Analysis workers",
                "processing",
                bool(age is not None and age < 90),
                f"last heartbeat {int(age)} s ago" if age is not None else "no worker heartbeat received",
            )
            try:
                add("queue", "Analysis queue", "processing", True, f"{r.llen('aegis')} message(s) waiting in broker")
            except Exception:  # noqa: BLE001
                add("queue", "Analysis queue", "processing", None, "queue length unavailable")
        else:
            add("worker", "Analysis workers", "processing", False, "broker unreachable")
    else:
        add(
            "worker",
            "Analysis workers",
            "processing",
            True,
            f"task mode '{s.task_mode}' (in-process; not for production)",
        )
    storage = get_storage()
    ok, detail = storage.health()
    add("storage", f"Evidence storage ({storage.name})", "evidence", ok, detail)
    add(
        "ffmpeg",
        "ffmpeg / ffprobe",
        "processing",
        bool(shutil.which("ffmpeg") and shutil.which("ffprobe")),
        "found on PATH" if shutil.which("ffmpeg") else "not installed: audio and video methods unavailable",
    )
    add(
        "malware_scanner",
        "Malware scanner (ClamAV)",
        "evidence",
        True if scanner_configured() else None,
        "configured" if scanner_configured() else "not configured: uploads are recorded as not scanned",
    )
    try:
        import c2pa

        add("c2pa", "C2PA verification library", "provenance", True, f"c2pa-rs {c2pa.sdk_version()}")
    except Exception:  # noqa: BLE001
        add("c2pa", "C2PA verification library", "provenance", False, "c2pa-python not importable")
    return out


def methods() -> list[dict[str, Any]]:
    rows = []
    for m in registry().values():
        ok, reason = m.availability()
        rows.append({**m.info.to_dict(), "available": ok, "availability_reason": reason})
    return rows


def queue_stats(db: Session) -> dict[str, int]:
    rows = db.execute(select(AnalysisJob.status, func.count()).group_by(AnalysisJob.status)).all()
    return {status: n for status, n in rows}
