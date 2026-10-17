"""Analysis job orchestration. Jobs are persisted; workers execute them idempotently.

A detector that fails, is unavailable, or is blocked by policy is recorded as such and is never
counted as a negative detection.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
import uuid
from functools import lru_cache
from typing import Any

from aegis_ml.core import AnalysisInput, AnalysisMethod, Modality, RunStatus
from aegis_ml.fusion import fuse
from aegis_ml.registry import PROFILES, build_registry, methods_for
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.config import get_settings
from app.core.errors import AppError, bad_request, conflict
from app.db import get_sessionmaker, utcnow
from app.models import (
    AnalysisArtifact,
    AnalysisJob,
    AnalysisSignal,
    CalibrationProfile,
    DetectorRun,
    DetectorVersion,
    EvidenceItem,
    Investigation,
    Organization,
    ProvenanceRecord,
    SegmentFinding,
)
from app.security.deps import Principal
from app.services import investigations as cases
from app.services.evidence import current_original, text_version
from app.services.notifications import notify
from app.storage.base import ObjectExists, get_storage

log = logging.getLogger("aegis.analysis")
TERMINAL_RUN = {
    "completed",
    "failed",
    "unavailable",
    "insufficient_input",
    "unsupported_input",
    "blocked_by_policy",
    "cancelled",
}
TERMINAL_JOB = {"completed", "completed_with_failures", "failed", "cancelled"}


@lru_cache
def registry() -> dict[str, AnalysisMethod]:
    return build_registry()


def jsonable(o: Any) -> Any:
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else o
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple | set):
        return [jsonable(v) for v in o]
    if hasattr(o, "item") and callable(o.item):
        return jsonable(o.item())
    if isinstance(o, str | int | bool) or o is None:
        return o
    return str(o)


def external_permitted(db: Session, inv: Investigation) -> bool:
    org = db.get(Organization, inv.organization_id)
    return bool(
        get_settings().allow_external_processing
        and org
        and org.allow_external_processing
        and inv.allow_external_processing
    )


def create_job(
    db: Session,
    p: Principal,
    inv: Investigation,
    item: EvidenceItem,
    profile_id: str,
    options: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> AnalysisJob:
    if idempotency_key:
        existing = db.execute(
            select(AnalysisJob).where(AnalysisJob.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            if existing.organization_id != p.org_id or existing.evidence_item_id != item.id:
                raise conflict("Idempotency key already used for a different request.")
            return existing
    if profile_id not in PROFILES:
        raise bad_request(f"Unknown analysis profile '{profile_id}'.")
    if item.investigation_id != inv.id:
        raise bad_request("Evidence does not belong to this investigation.")
    if item.status != "active":
        raise conflict(f"Evidence status is {item.status}; analysis is blocked until integrity is resolved.")
    cases.ensure_unlocked(inv)
    modality = Modality(item.modality)
    methods = methods_for(profile_id, modality, registry())
    if not methods:
        raise bad_request(f"Profile '{profile_id}' has no methods for {modality} evidence.")
    original = current_original(item)
    job = AnalysisJob(
        id=uuid.uuid4(),
        organization_id=inv.organization_id,
        investigation_id=inv.id,
        evidence_item_id=item.id,
        evidence_version_id=original.id,
        profile_id=profile_id,
        status="queued",
        methods_total=len(methods),
        methods_done=0,
        options=options or {},
        external_processing_permitted=external_permitted(db, inv),
        idempotency_key=idempotency_key,
        requested_by_id=p.user.id,
    )
    db.add(job)
    db.flush()
    for i, m in enumerate(methods):
        db.add(
            DetectorRun(
                job_id=job.id,
                position=i,
                method_id=m.info.id,
                method_version=m.info.version,
                method_name=m.info.name,
                evidence_class=str(m.info.evidence_class),
                status="pending",
                input_sha256=original.sha256,
                limitations=list(m.info.limitations),
            )
        )
    cases.advance_if(db, inv, {"evidence_acquired", "analysis_complete", "human_review"}, "analysis_queued")
    audit.record(
        db,
        "analysis.queued",
        "analysis_job",
        job.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        details={
            "profile": profile_id,
            "evidence_id": str(item.id),
            "input_sha256": original.sha256,
            "methods": [m.info.id for m in methods],
            "external_processing_permitted": job.external_processing_permitted,
        },
    )
    return job


def dispatch(job_id: uuid.UUID) -> str | None:
    """Hand the job to the worker pool. Called after the creating transaction commits."""
    mode = get_settings().task_mode
    if mode == "inline":
        t = threading.Thread(target=execute_job, args=(job_id,), daemon=True, name=f"aegis-job-{job_id}")
        t.start()
        return None
    if mode == "manual":  # tests drive execution explicitly
        return None
    from app.workers.tasks import run_analysis_job

    return run_analysis_job.delay(str(job_id)).id


def _registry_overrides(db: Session) -> dict[str, DetectorVersion]:
    return {d.method_id: d for d in db.execute(select(DetectorVersion)).scalars()}


def _calibration_profiles(db: Session, overrides: dict[str, DetectorVersion]) -> dict[str, dict[str, Any]]:
    """Validated calibration profiles attached to registry entries, keyed by method id."""
    out = {}
    for mid, reg in overrides.items():
        if reg.validation_status != "validated" or not reg.calibration_profile_id:
            continue
        prof = db.get(CalibrationProfile, reg.calibration_profile_id)
        if prof is None or not prof.validated:
            continue
        out[mid] = {
            "method": prof.calibration_method,
            **(prof.parameters or {}),
            "threshold": prof.threshold,
            "validated": True,
            "population": prof.population,
            "languages_evaluated": prof.languages or None,
            "benchmark_run_id": str(prof.benchmark_run_id),
            "profile_id": str(prof.id),
            "direction": (prof.parameters or {}).get("direction", "higher_is_ai"),
        }
    return out


def _build_input(db: Session, job: AnalysisJob, item: EvidenceItem, path) -> AnalysisInput:  # type: ignore[no-untyped-def]
    text = None
    extraction = item.extraction or {}
    tv = text_version(item)
    if tv is not None:
        with get_storage().local_path(tv.storage_key) as tp:
            text = tp.read_text("utf-8")
    return AnalysisInput(
        modality=Modality(item.modality),
        mime_type=item.mime_type,
        original_path=path,
        sha256=current_original(item).sha256,
        text=text,
        language=(extraction.get("language") or {}).get("code"),
        extraction=extraction,
        options={**(job.options or {}), "calibration_profiles": _calibration_profiles(db, _registry_overrides(db))},
        allow_external_processing=job.external_processing_permitted and get_settings().allow_external_processing,
    )


def _dependencies(run: DetectorRun, all_runs: list[DetectorRun]) -> list[str]:
    reg = registry()
    m = reg.get(run.method_id)
    if not m:
        return []
    mine = {r for r in m.info.requires if r.startswith("AEGIS_")}
    deps = []
    for other in all_runs:
        o = reg.get(other.method_id)
        if other.id != run.id and o and mine & set(o.info.requires):
            deps.append(f"shares configuration/model with {other.method_id}")
    return deps


def _persist_result(db: Session, job: AnalysisJob, item: EvidenceItem, run: DetectorRun, res, all_runs) -> None:  # type: ignore[no-untyped-def]
    d = res.to_dict()
    run.status = str(res.status)
    run.summary = res.summary
    run.output = jsonable(d["output"])
    run.score = res.score if res.score is None or math.isfinite(res.score) else None
    run.score_semantics = res.score_semantics
    run.calibrated = bool(res.calibrated)
    run.flagged = res.flagged
    run.uncertainty = jsonable(res.uncertainty)
    run.warnings = list(res.warnings)
    run.limitations = list(res.limitations)
    run.config = jsonable(res.config)
    run.error = res.error
    run.duration_ms = res.duration_ms
    run.finished_at = utcnow()
    storage = get_storage()
    for a in res.artifacts:
        sha = hashlib.sha256(a.data).hexdigest()
        key = f"orgs/{job.organization_id}/artifacts/{sha[:2]}/{sha}"
        try:
            storage.put_bytes(key, a.data, a.media_type)
        except ObjectExists:
            pass
        run.artifacts.append(
            AnalysisArtifact(
                name=a.name,
                media_type=a.media_type,
                storage_key=key,
                sha256=sha,
                description=a.description,
                cannot_establish=a.cannot_establish,
            )
        )
    for s in res.segments[:2000]:
        run.segments.append(
            SegmentFinding(
                start=float(s.start),
                end=float(s.end),
                unit=s.unit,
                label=s.label,
                score=s.score,
                detail=jsonable(s.detail),
            )
        )
    if res.status == RunStatus.COMPLETED:
        out = run.output or {}
        verification = None
        if run.evidence_class == "cryptographic_provenance":
            verification = out.get("state")
            db.add(
                ProvenanceRecord(
                    evidence_item_id=item.id,
                    detector_run_id=run.id,
                    state=verification or "unknown",
                    summary=out,
                    trust_anchor=(run.config or {}).get("trust_anchors"),
                )
            )
        elif run.evidence_class == "verified_watermark":
            verification = "detected" if res.flagged else "not_detected"
        ex = item.extraction or {}
        db.add(
            AnalysisSignal(
                job_id=job.id,
                detector_run_id=run.id,
                evidence_class=run.evidence_class,
                verification_status=verification,
                calibration_status="validated"
                if run.calibrated
                else ("uncalibrated" if run.evidence_class == "statistical_inference" else "not_applicable"),
                applicable_population=(
                    (out.get("calibration_profile") or {}).get("population")
                    if isinstance(out.get("calibration_profile"), dict)
                    else None
                ),
                input_characteristics=jsonable(
                    {
                        "modality": item.modality,
                        "mime_type": item.mime_type,
                        "tokens": ex.get("token_count"),
                        "language": (ex.get("language") or {}).get("code"),
                    }
                ),
                uncertainty=run.uncertainty,
                known_dependencies=_dependencies(run, all_runs),
                supporting_reference=f"detector_run:{run.id}",
            )
        )


def execute_job(job_id: uuid.UUID | str) -> str:
    """Run (or resume) a job. Safe to call repeatedly: completed runs are never repeated."""
    job_id = uuid.UUID(str(job_id))
    Session_ = get_sessionmaker()
    with Session_() as db:
        job = db.get(AnalysisJob, job_id)
        if job is None:
            return "missing"
        if job.status in TERMINAL_JOB:
            return job.status
        job.status = "running"
        job.attempts += 1
        job.started_at = job.started_at or utcnow()
        db.commit()
        item = db.get(EvidenceItem, job.evidence_item_id)
        assert item is not None
        overrides = _registry_overrides(db)
        try:
            with get_storage().local_path(current_original(item).storage_key) as path:
                inp = _build_input(db, job, item, path)
                runs = list(job.runs)
                for run in runs:
                    if run.status in TERMINAL_RUN:
                        continue
                    db.refresh(job)
                    if job.cancel_requested:
                        for r in runs:
                            if r.status not in TERMINAL_RUN:
                                r.status, r.summary = "cancelled", "Cancelled before execution."
                        job.status = "cancelled"
                        break
                    run.status, run.started_at = "running", utcnow()
                    db.commit()
                    method = registry().get(run.method_id)
                    reg = overrides.get(run.method_id)
                    if method is None:
                        run.status, run.summary = "unavailable", "Method is no longer registered."
                    elif reg is not None and not reg.enabled:
                        run.status, run.summary = "unavailable", "Method disabled by an administrator."
                    else:
                        res = method.run(inp)
                        _persist_result(db, job, item, run, res, runs)
                        if reg is not None and reg.validation_status == "validated":
                            run.threshold = reg.operating_threshold
                    run.finished_at = run.finished_at or utcnow()
                    job.methods_done = sum(1 for r in runs if r.status in TERMINAL_RUN)
                    db.commit()
        except Exception as exc:  # noqa: BLE001 - recorded on the job; never silently dropped
            log.exception("analysis job failed", extra={"ctx_job": str(job_id)})
            db.rollback()
            job = db.get(AnalysisJob, job_id)
            assert job is not None
            job.status, job.error, job.finished_at = "failed", f"{type(exc).__name__}: {str(exc)[:500]}", utcnow()
            audit.record(
                db,
                "analysis.failed",
                "analysis_job",
                job.id,
                actor_label="system:worker",
                organization_id=job.organization_id,
                investigation_id=job.investigation_id,
                details={"error": job.error},
            )
            notify(
                db,
                job.requested_by_id,
                job.organization_id,
                "job_failed",
                "Analysis job failed",
                job.error,
                link=f"/cases/{job.investigation_id}",
                severity="error",
            )
            _maybe_complete_case(db, job)
            db.commit()
            return "failed"
        if job.status != "cancelled":
            results = [_run_dict(r) for r in job.runs]
            job.fusion = jsonable(fuse(results).to_dict())
            failed = any(r.status == "failed" for r in job.runs)
            job.status = "completed_with_failures" if failed else "completed"
        job.finished_at = utcnow()
        audit.record(
            db,
            f"analysis.{job.status}",
            "analysis_job",
            job.id,
            actor_label="system:worker",
            organization_id=job.organization_id,
            investigation_id=job.investigation_id,
            details={
                "runs": {r.method_id: r.status for r in job.runs},
                "automated_outcome": (job.fusion or {}).get("primary_outcome"),
            },
        )
        inv = db.get(Investigation, job.investigation_id)
        recipients = {job.requested_by_id} | ({inv.assigned_reviewer_id} if inv and inv.assigned_reviewer_id else set())
        for uid in recipients:
            notify(
                db,
                uid,
                job.organization_id,
                "job_completed",
                f"Analysis {job.status.replace('_', ' ')}",
                (job.fusion or {}).get("primary_label", ""),
                link=f"/cases/{job.investigation_id}",
            )
        _maybe_complete_case(db, job)
        db.commit()
        return job.status


def _maybe_complete_case(db: Session, job: AnalysisJob) -> None:
    inv = db.get(Investigation, job.investigation_id)
    if inv is None or inv.status != "analysis_queued":
        return
    active = db.execute(
        select(func.count())
        .select_from(AnalysisJob)
        .where(
            AnalysisJob.investigation_id == inv.id,
            AnalysisJob.status.in_(("queued", "running")),
            AnalysisJob.id != job.id,
        )
    ).scalar_one()
    if not active:
        cases.transition(db, inv, "analysis_complete", actor=None, automatic=True)


def _run_dict(r: DetectorRun) -> dict[str, Any]:
    return {
        "method_id": r.method_id,
        "evidence_class": r.evidence_class,
        "status": r.status,
        "flagged": r.flagged,
        "calibrated": r.calibrated,
        "output": r.output or {},
        "summary": r.summary or "",
    }


def cancel_job(db: Session, p: Principal, job: AnalysisJob) -> AnalysisJob:
    if job.status in TERMINAL_JOB:
        raise conflict(f"Job already {job.status}.")
    job.cancel_requested = True
    if job.status == "queued":
        for r in job.runs:
            if r.status not in TERMINAL_RUN:
                r.status, r.summary = "cancelled", "Cancelled before execution."
        job.status, job.finished_at = "cancelled", utcnow()
        _maybe_complete_case(db, job)
    audit.record(
        db,
        "analysis.cancel_requested",
        "analysis_job",
        job.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=job.investigation_id,
        ip=p.ip,
    )
    return job


def recover_stale_jobs(db: Session, older_than_minutes: int = 30) -> int:
    """Requeue jobs left 'running' by a lost worker (runs already completed are kept)."""
    from datetime import timedelta

    cutoff = utcnow() - timedelta(minutes=older_than_minutes)
    stale = (
        db.execute(select(AnalysisJob).where(AnalysisJob.status == "running", AnalysisJob.started_at < cutoff))
        .scalars()
        .all()
    )
    for job in stale:
        if job.attempts >= 3:
            job.status, job.error = "failed", "Exceeded retry attempts after worker loss."
            continue
        for r in job.runs:
            if r.status == "running":
                r.status = "pending"
        job.status = "queued"
    db.commit()
    for job in stale:
        if job.status == "queued":
            dispatch(job.id)
    return len(stale)


def require_job(db: Session, p: Principal, job_id: uuid.UUID) -> AnalysisJob:
    job = db.get(AnalysisJob, job_id)
    if job is None or job.organization_id != p.org_id:
        raise AppError(404, "not_found", "analysis job not found")
    cases.get_case(db, p, job.investigation_id)  # enforces classification visibility
    return job
