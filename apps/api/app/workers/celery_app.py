"""Celery application: Redis broker, late acknowledgement, persisted job state in PostgreSQL."""

from __future__ import annotations

import logging
import threading
import time

from celery import Celery
from celery.signals import worker_ready, worker_shutdown

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
celery_app = Celery("aegis", broker=settings.redis_url, backend=None, include=["app.workers.tasks"])
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3600,
    task_soft_time_limit=3300,
    broker_connection_retry_on_startup=True,
    task_default_queue="aegis",
    task_routes={"app.workers.tasks.run_benchmark": {"queue": "aegis-research"}},
    beat_schedule={"recover-stale-jobs": {"task": "app.workers.tasks.recover_stale", "schedule": 600.0}},
)

_stop = threading.Event()
HEARTBEAT_KEY = "aegis:worker:heartbeat"


def _heartbeat() -> None:
    import redis

    r = redis.Redis.from_url(settings.redis_url)
    while not _stop.is_set():
        try:
            r.set(HEARTBEAT_KEY, str(time.time()), ex=60)
        except Exception:  # noqa: BLE001
            logging.getLogger("aegis.worker").warning("heartbeat failed")
        _stop.wait(20)


@worker_ready.connect
def _start(**_):  # type: ignore[no-untyped-def]
    configure_logging()
    threading.Thread(target=_heartbeat, daemon=True, name="aegis-heartbeat").start()


@worker_shutdown.connect
def _shutdown(**_):  # type: ignore[no-untyped-def]
    _stop.set()
