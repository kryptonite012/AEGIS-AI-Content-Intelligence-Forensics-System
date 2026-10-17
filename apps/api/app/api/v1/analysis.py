from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any

from aegis_ml.registry import PROFILES
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.db import get_db, get_sessionmaker
from app.models import AnalysisJob, DetectorRun, EvidenceItem
from app.schemas.common import ORM
from app.security.deps import Principal, require
from app.services import analysis as svc
from app.services import investigations as cases

router = APIRouter(prefix="/analysis", tags=["analysis"])


class SegmentOut(ORM):
    start: float
    end: float
    unit: str
    label: str
    score: float | None
    detail: dict[str, Any]


class ArtifactOut(ORM):
    id: uuid.UUID
    name: str
    media_type: str
    sha256: str
    description: str
    cannot_establish: str


class RunOut(ORM):
    id: uuid.UUID
    position: int
    method_id: str
    method_version: str
    method_name: str
    evidence_class: str
    status: str
    input_sha256: str
    config: dict[str, Any]
    threshold: float | None
    summary: str | None
    output: dict[str, Any]
    output_schema: str
    score: float | None
    score_semantics: str | None
    calibrated: bool
    flagged: bool | None
    uncertainty: dict[str, Any] | None
    warnings: list[str]
    limitations: list[str]
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    artifacts: list[ArtifactOut]


class JobOut(ORM):
    id: uuid.UUID
    investigation_id: uuid.UUID
    evidence_item_id: uuid.UUID
    evidence_version_id: uuid.UUID
    profile_id: str
    status: str
    methods_total: int
    methods_done: int
    options: dict[str, Any]
    external_processing_permitted: bool
    attempts: int
    cancel_requested: bool
    fusion: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    runs: list[RunOut]


class JobSummary(ORM):
    id: uuid.UUID
    evidence_item_id: uuid.UUID
    profile_id: str
    status: str
    methods_total: int
    methods_done: int
    created_at: datetime
    finished_at: datetime | None


@router.get("/profiles")
def profiles(p: Principal = Depends(require("analysis.read"))) -> list[dict]:
    reg = svc.registry()
    out = []
    for prof in PROFILES.values():
        methods = []
        for mid in prof.methods:
            m = reg.get(mid)
            if m is None:
                continue
            ok, reason = m.availability()
            methods.append(
                {
                    "id": mid,
                    "name": m.info.name,
                    "evidence_class": str(m.info.evidence_class),
                    "implementation": str(m.info.implementation),
                    "available": ok,
                    "reason": reason,
                    "modalities": [str(x) for x in m.info.modalities],
                    "external_processing": m.info.external_processing,
                }
            )
        out.append(
            {
                "id": prof.id,
                "name": prof.name,
                "description": prof.description,
                "modalities": [str(m) for m in prof.modalities],
                "resources": prof.resources,
                "limitations": list(prof.limitations),
                "methods": methods,
            }
        )
    return out


class JobIn(BaseModel):
    evidence_item_id: uuid.UUID
    profile_id: str = Field(max_length=60)
    options: dict[str, Any] = Field(default_factory=dict)


@router.post("/investigations/{case_id}/jobs", response_model=JobOut, status_code=202)
def create_job(
    case_id: uuid.UUID,
    body: JobIn,
    p: Principal = Depends(require("analysis.run")),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, max_length=120),
):
    inv = cases.get_case(db, p, case_id, for_update=True)
    item = db.get(EvidenceItem, body.evidence_item_id)
    if item is None or item.investigation_id != inv.id:
        raise not_found("evidence")
    allowed_opts = {k: v for k, v in body.options.items() if k in ("sample_fps",)}
    job = svc.create_job(db, p, inv, item, body.profile_id, allowed_opts, idempotency_key)
    db.commit()
    if job.task_id is None and job.status == "queued":
        tid = svc.dispatch(job.id)
        if tid:
            job.task_id = tid
            db.commit()
    db.refresh(job)
    return job


@router.get("/investigations/{case_id}/jobs", response_model=list[JobSummary])
def list_jobs(case_id: uuid.UUID, p: Principal = Depends(require("analysis.read")), db: Session = Depends(get_db)):
    cases.get_case(db, p, case_id)
    return (
        db.execute(
            select(AnalysisJob).where(AnalysisJob.investigation_id == case_id).order_by(AnalysisJob.created_at.desc())
        )
        .scalars()
        .all()
    )


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: uuid.UUID, p: Principal = Depends(require("analysis.read")), db: Session = Depends(get_db)):
    return svc.require_job(db, p, job_id)


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: uuid.UUID, p: Principal = Depends(require("analysis.run")), db: Session = Depends(get_db)):
    job = svc.cancel_job(db, p, svc.require_job(db, p, job_id))
    db.commit()
    db.refresh(job)
    return job


@router.get("/runs/{run_id}/segments", response_model=list[SegmentOut])
def run_segments(run_id: uuid.UUID, p: Principal = Depends(require("analysis.read")), db: Session = Depends(get_db)):
    run = db.get(DetectorRun, run_id)
    if run is None:
        raise not_found("run")
    svc.require_job(db, p, run.job_id)
    return run.segments


def _snapshot(job: AnalysisJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "status": job.status,
        "methods_total": job.methods_total,
        "methods_done": job.methods_done,
        "runs": [{"method_id": r.method_id, "status": r.status} for r in job.runs],
        "primary_outcome": (job.fusion or {}).get("primary_outcome"),
    }


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: uuid.UUID, request: Request, p: Principal = Depends(require("analysis.read")), db: Session = Depends(get_db)
) -> StreamingResponse:
    """Server-sent events reflecting persisted job state. Each event is emitted only when the stored
    state actually changes; no progress is simulated."""
    svc.require_job(db, p, job_id)
    db.close()

    async def stream():  # type: ignore[no-untyped-def]
        last = None
        idle = 0
        while not await request.is_disconnected():
            with get_sessionmaker()() as s:
                job = s.get(AnalysisJob, job_id)
                snap = _snapshot(job) if job else None
            if snap != last:
                last = snap
                idle = 0
                yield f"event: job\ndata: {json.dumps(snap)}\n\n"
                if snap is None or snap["status"] in svc.TERMINAL_JOB:
                    return
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ": keep-alive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
    )
