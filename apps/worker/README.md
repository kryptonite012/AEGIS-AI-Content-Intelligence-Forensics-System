# AEGIS worker

The worker runs the API image (`infrastructure/docker/api.Dockerfile`) with a Celery command, so API and worker always share the exact same code and analysis-method versions:

```bash
celery -A app.workers.celery_app worker -Q aegis,aegis-research -c 2 --loglevel=INFO   # analysis + research queues
celery -A app.workers.celery_app beat                                                 # stale-job recovery every 10 min
```

- Tasks: `run_analysis_job` (queue `aegis`), `run_benchmark` (queue `aegis-research`), `recover_stale`.
- Late acknowledgement and `reject_on_worker_lost` mean that a task interrupted by a crashed worker is redelivered.
- Detector runs are unique per `(job, method)`. On redelivery, completed runs are skipped and pending runs resume.
- The worker writes a heartbeat to Redis every 20 s; `/api/v1/health/components` reports it.
- Scale horizontally by adding worker containers. Use `-c` to set per-container concurrency according to model memory.
