"""Fixed-window rate limiting backed by Redis, with an in-process fallback for development/tests."""

from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache

from app.core.config import get_settings
from app.core.errors import AppError

log = logging.getLogger("aegis.ratelimit")


class _Memory:
    def __init__(self) -> None:
        self._d: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, window: int) -> int:
        now = time.time()
        with self._lock:
            count, reset = self._d.get(key, (0, now + window))
            if now > reset:
                count, reset = 0, now + window
            count += 1
            self._d[key] = (count, reset)
            return count

    def reset(self) -> None:
        with self._lock:
            self._d.clear()


_memory = _Memory()


@lru_cache
def _redis():
    url = get_settings().redis_url
    if not url:
        return None
    try:
        import redis

        r = redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5)
        r.ping()
        return r
    except Exception:  # noqa: BLE001 - fall back to in-process limiting
        log.warning("redis unavailable; using in-process rate limiting")
        return None


def check(name: str, subject: str, limit: int, window_seconds: int) -> None:
    key = f"aegis:rl:{name}:{subject}:{int(time.time() // window_seconds)}"
    r = _redis() if get_settings().environment != "test" else None
    if r is not None:
        try:
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds + 1)
            count = int(pipe.execute()[0])
        except Exception:  # noqa: BLE001
            count = _memory.hit(key, window_seconds)
    else:
        count = _memory.hit(key, window_seconds)
    if count > limit:
        raise AppError(
            429,
            "rate_limited",
            "Too many requests; please retry later.",
            {"limit": limit, "window_seconds": window_seconds},
        )


def reset_memory() -> None:
    _memory.reset()
