from __future__ import annotations

from sqlalchemy.exc import OperationalError

from app.workers.celery_app import celery_app


@celery_app.task(
    bind=True,
    autoretry_for=(OperationalError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
    name="app.workers.tasks.run_analysis_job",
)
def run_analysis_job(self, job_id: str) -> str:  # type: ignore[no-untyped-def]
    from app.services.analysis import execute_job

    return execute_job(job_id)


@celery_app.task(bind=True, name="app.workers.tasks.run_benchmark")
def run_benchmark(self, run_id: str) -> str:  # type: ignore[no-untyped-def]
    from app.services.benchmarks import execute_benchmark

    return execute_benchmark(run_id)


@celery_app.task(name="app.workers.tasks.recover_stale")
def recover_stale() -> int:
    from app.db import session_scope
    from app.services.analysis import recover_stale_jobs

    with session_scope() as db:
        return recover_stale_jobs(db)
