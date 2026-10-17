"""Statistical Reliability Laboratory, Research Bench and Benchmark Laboratory endpoints."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Literal

from aegis_research import reliability as rel
from aegis_research.experiments import EXPERIMENTS
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, bad_request, not_found
from app.db import get_db
from app.models import BenchmarkRun, BenchmarkSample, CalibrationProfile, Dataset, ExperimentRun
from app.schemas.common import ORM
from app.security.deps import Principal, require
from app.services import benchmarks as bench
from app.services.analysis import jsonable

router = APIRouter(tags=["research"])
SourceKind = Literal["measured", "assumed", "published", "vendor_reported", "simulated"]


# ----------------------------------------------------------------------------- calculators


class PPVIn(BaseModel):
    prevalence: float = Field(ge=0, le=1)
    tpr: float = Field(ge=0, le=1)
    fpr: float = Field(ge=0, le=1)
    sample_size: int | None = Field(default=None, ge=0, le=10**9)
    tpr_source: SourceKind = "assumed"
    fpr_source: SourceKind = "assumed"
    prevalence_source: SourceKind = "assumed"
    benchmark_run_id: uuid.UUID | None = None


@router.post("/evaluation/ppv")
def ppv_calculator(body: PPVIn, p: Principal = Depends(require("research.use"))) -> dict:
    res = rel.predictive_values(
        body.tpr,
        body.fpr,
        body.prevalence,
        body.sample_size,
        {"tpr": body.tpr_source, "fpr": body.fpr_source, "prevalence": body.prevalence_source},
    )
    grid = [0.001, 0.0025, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5]
    return {
        **res.to_dict(),
        "sensitivity": rel.ppv_sensitivity(body.tpr, body.fpr, grid),
        "formula": "PPV = (TPR × prevalence) / [(TPR × prevalence) + (FPR × (1 − prevalence))]",
        "statement": "PPV depends on the deployment population and on the validity of the input rates for that "
        "population. It is not the probability for an individual item unless those rates hold for it.",
    }


class ThresholdIn(BaseModel):
    benchmark_run_id: uuid.UUID
    deployment_prevalence: float = Field(ge=0, le=1)
    population_size: int = Field(default=10_000, ge=1, le=10**9)
    split: str = "test"


def _samples(db: Session, run_id: uuid.UUID, split: str | None = "test", transform: str | None = "original"):
    q = select(BenchmarkSample).where(BenchmarkSample.run_id == run_id, BenchmarkSample.score.is_not(None))
    if split:
        q = q.where(BenchmarkSample.split == split)
    if transform:
        q = q.where(BenchmarkSample.transform == transform)
    return db.execute(q).scalars().all()


def _run(db: Session, run_id: uuid.UUID) -> BenchmarkRun:
    run = db.get(BenchmarkRun, run_id)
    if run is None:
        raise not_found("benchmark run")
    return run


@router.post("/evaluation/threshold-explorer")
def threshold_explorer(
    body: ThresholdIn, p: Principal = Depends(require("research.use")), db: Session = Depends(get_db)
) -> dict:
    run = _run(db, body.benchmark_run_id)
    ss = _samples(db, run.id, body.split)
    y, s = [x.label for x in ss], [float(x.score) for x in ss]  # type: ignore[arg-type]
    if len(set(y)) < 2:
        raise bad_request("The selected run has no labelled scores for both classes on this split.")
    return {
        "run_id": str(run.id),
        "result_kind": run.result_kind,
        "method_id": run.method_id,
        "n": len(y),
        "negatives": y.count(0),
        "positives": y.count(1),
        "rows": jsonable(rel.threshold_sweep(y, s, None, body.deployment_prevalence, body.population_size)),
        "statement": "No universal threshold is recommended. Lower thresholds catch more synthetic content and "
        "raise false accusations; the acceptable trade-off depends on the consequences of each error.",
    }


@router.get("/evaluation/fairness/{run_id}")
def fairness(
    run_id: uuid.UUID,
    threshold: float | None = None,
    min_group_size: int = Query(10, ge=1, le=1000),
    p: Principal = Depends(require("research.use")),
    db: Session = Depends(get_db),
) -> dict:
    run = _run(db, run_id)
    thr = threshold if threshold is not None else (run.metrics or {}).get("threshold")
    if thr is None:
        raise bad_request("No threshold: supply one or use a run whose threshold was selected on a validation split.")
    ss = _samples(db, run.id)
    rows = rel.subgroup_metrics(
        [x.label for x in ss],
        [int(float(x.score) >= thr) for x in ss],  # type: ignore[arg-type]
        [x.group or "unspecified" for x in ss],
        min_group_size,
    )
    return {
        "run_id": str(run.id),
        "result_kind": run.result_kind,
        "threshold": thr,
        "min_group_size": min_group_size,
        "groups": jsonable(rows),
        "statement": "Subgroups come only from fields supplied with lawfully collected, consented evaluation data. "
        "AEGIS never infers sensitive attributes from content. Small groups are suppressed.",
    }


@router.get("/evaluation/robustness/{run_id}")
def robustness(
    run_id: uuid.UUID, p: Principal = Depends(require("research.use")), db: Session = Depends(get_db)
) -> dict:
    run = _run(db, run_id)
    m = run.metrics or {}
    return {
        "run_id": str(run.id),
        "result_kind": run.result_kind,
        "original": m.get("overall"),
        "transforms": m.get("robustness", {}),
        "statement": "Measures defensive robustness to the listed, documented transformations only. No claim of "
        "robustness against other or adaptive attacks follows.",
    }


@router.get("/evaluation/experiments")
def list_experiments(p: Principal = Depends(require("research.use"))) -> list[dict]:
    out = []
    for eid, fn in EXPERIMENTS.items():
        doc = (fn.__doc__ or "").strip()
        out.append({"id": eid, "function": fn.__name__, "doc": doc})
    return out


class ExperimentIn(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


_EXPERIMENT_ARGS: dict[str, set[str]] = {
    "exp1_base_rate": {"tpr", "fpr", "prevalence", "population"},
    "exp2_subgroup": {"groups"},
    "exp3_corroboration": {"tpr1", "fpr1", "tpr2", "fpr2", "prevalence", "seed"},
    "exp4_auroc_strict_fpr": {"n_pos", "n_neg", "seed"},
    "exp5_watermark_length_entropy": {"trials", "seed"},
    "exp6_watermark_robustness": {"length", "trials", "zipf_exponent", "seed"},
    "exp7_threshold_selection": {"gamma"},
    "exp8_strength_distortion": {"length", "trials", "zipf_exponent", "seed"},
    "exp9_fpr_calibration": {"gamma"},
}


@router.post("/evaluation/experiments/{experiment_id}/runs")
def run_experiment(
    experiment_id: str,
    body: ExperimentIn,
    p: Principal = Depends(require("research.use")),
    db: Session = Depends(get_db),
) -> dict:
    if experiment_id not in EXPERIMENTS:
        raise not_found("experiment")
    unknown = set(body.config) - _EXPERIMENT_ARGS[experiment_id]
    if unknown:
        raise bad_request(f"Unsupported parameters: {sorted(unknown)}")
    cfg = body.config
    for k in ("trials", "n_pos", "n_neg", "length", "population"):
        if k in cfg and not (
            1 <= int(cfg[k]) <= {"trials": 200, "n_pos": 20000, "n_neg": 20000, "length": 1000, "population": 10**8}[k]
        ):
            raise bad_request(f"Parameter {k} out of range.")
    try:
        result = jsonable(EXPERIMENTS[experiment_id](**cfg))
    except (TypeError, ValueError) as exc:
        raise bad_request(f"Invalid configuration: {exc}") from exc
    payload = json.dumps(result, sort_keys=True, default=str)
    er = ExperimentRun(
        experiment_id=experiment_id,
        kind=result["kind"],
        config=result["config"],
        results=result,
        manifest={"sha256": hashlib.sha256(payload.encode()).hexdigest()},
        created_by_id=p.user.id,
    )
    db.add(er)
    db.commit()
    return {"run_id": str(er.id), **result}


@router.get("/evaluation/experiment-runs")
def experiment_runs(
    p: Principal = Depends(require("research.use")), db: Session = Depends(get_db), experiment_id: str | None = None
) -> list[dict]:
    q = select(ExperimentRun).order_by(ExperimentRun.created_at.desc()).limit(100)
    if experiment_id:
        q = q.where(ExperimentRun.experiment_id == experiment_id)
    return [
        {
            "id": str(r.id),
            "experiment_id": r.experiment_id,
            "kind": r.kind,
            "created_at": r.created_at,
            "sha256": (r.manifest or {}).get("sha256"),
        }
        for r in db.execute(q).scalars()
    ]


@router.get("/evaluation/experiment-runs/{run_id}")
def experiment_run(run_id: uuid.UUID, p: Principal = Depends(require("research.use")), db: Session = Depends(get_db)):
    r = db.get(ExperimentRun, run_id)
    if r is None:
        raise not_found("experiment run")
    return {"id": str(r.id), "created_at": r.created_at, **r.results}


# ----------------------------------------------------------------------------- benchmarks


class DatasetOut(ORM):
    id: uuid.UUID
    name: str
    version: str
    modality: str
    provenance: str
    license: str
    consent_basis: str
    documentation: str
    is_synthetic: bool
    sha256: str
    n_samples: int
    splits: dict[str, int]
    fields: list[str]
    duplicate_report: dict[str, Any]
    created_at: datetime


class RunOut(ORM):
    id: uuid.UUID
    dataset_id: uuid.UUID | None
    method_id: str
    method_version: str
    result_kind: str
    status: str
    seed: int
    config: dict[str, Any]
    manifest: dict[str, Any]
    metrics: dict[str, Any]
    source_citation: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


@router.get("/benchmarks/datasets", response_model=list[DatasetOut])
def datasets(p: Principal = Depends(require("benchmark.read")), db: Session = Depends(get_db)):
    return db.execute(select(Dataset).order_by(Dataset.created_at.desc())).scalars().all()


@router.post("/benchmarks/datasets", response_model=DatasetOut, status_code=201)
def register_dataset(
    file: UploadFile = File(...),
    name: str = Form(..., max_length=200),
    version: str = Form(..., max_length=60),
    provenance: str = Form(..., max_length=4000),
    license: str = Form(..., max_length=200),
    consent_basis: str = Form(..., max_length=4000),
    documentation: str = Form("", max_length=20000),
    is_synthetic: bool = Form(False),
    p: Principal = Depends(require("dataset.register")),
    db: Session = Depends(get_db),
):
    raw = file.file.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise AppError(413, "payload_too_large", "Datasets are limited to 64 MB.")
    ds = bench.register_dataset(
        db,
        p.user,
        raw,
        {
            "name": name,
            "version": version,
            "provenance": provenance,
            "license": license,
            "consent_basis": consent_basis,
            "documentation": documentation,
            "is_synthetic": is_synthetic,
        },
        p.org_id,
    )
    db.commit()
    db.refresh(ds)
    return ds


@router.get("/benchmarks/runs", response_model=list[RunOut])
def runs(
    p: Principal = Depends(require("benchmark.read")), db: Session = Depends(get_db), method_id: str | None = None
):
    q = select(BenchmarkRun).order_by(BenchmarkRun.created_at.desc()).limit(200)
    if method_id:
        q = q.where(BenchmarkRun.method_id == method_id)
    return db.execute(q).scalars().all()


@router.get("/benchmarks/runs/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, p: Principal = Depends(require("benchmark.read")), db: Session = Depends(get_db)):
    return _run(db, run_id)


class RunIn(BaseModel):
    method_id: str
    dataset_id: uuid.UUID
    split: Literal["test", "validation"] = "test"
    threshold: float | None = None
    target_fpr: float = Field(0.01, gt=0, lt=1)
    seed: int = 0
    holdout_field: Literal["generator", "domain", "language"] | None = None
    holdout_values: list[str] = Field(default_factory=list, max_length=50)


@router.post("/benchmarks/runs", response_model=RunOut, status_code=202)
def create_run(body: RunIn, p: Principal = Depends(require("benchmark.run")), db: Session = Depends(get_db)):
    ds = db.get(Dataset, body.dataset_id)
    if ds is None:
        raise not_found("dataset")
    cfg: dict[str, Any] = {
        "split": body.split,
        "threshold": body.threshold,
        "target_fpr": body.target_fpr,
        "seed": body.seed,
    }
    if body.holdout_field:
        cfg["holdout"] = {"field": body.holdout_field, "values": body.holdout_values}
    run = bench.create_run(db, p.user, p.org_id, body.method_id, ds, cfg)
    db.commit()
    if get_settings().task_mode == "celery":
        from app.workers.tasks import run_benchmark

        run_benchmark.delay(str(run.id))
    elif get_settings().task_mode == "inline":
        import threading

        threading.Thread(target=bench.execute_benchmark, args=(run.id,), daemon=True).start()
    db.refresh(run)
    return run


@router.post("/benchmarks/reference-watermark", response_model=RunOut, status_code=201)
def reference_watermark_benchmark(p: Principal = Depends(require("benchmark.run")), db: Session = Depends(get_db)):
    """Built-in, clearly labelled SIMULATED benchmark of the AEGIS reference watermark verifier."""
    return bench.run_reference_watermark_benchmark(db, p.user, p.org_id)


@router.post("/benchmarks/imported-scores", response_model=RunOut, status_code=201)
def imported_scores(
    file: UploadFile = File(...),
    name: str = Form(..., max_length=60),
    result_kind: Literal["locally_measured", "vendor_reported", "published", "reproduced"] = Form(...),
    citation: str | None = Form(None, max_length=2000),
    p: Principal = Depends(require("benchmark.run")),
    db: Session = Depends(get_db),
):
    raw = file.file.read(16 * 1024 * 1024 + 1)
    if len(raw) > 16 * 1024 * 1024:
        raise AppError(413, "payload_too_large", "Score files are limited to 16 MB.")
    run = bench.import_scores(db, p.user, p.org_id, name, raw, result_kind, citation)
    db.commit()
    db.refresh(run)
    return run


class CalibrationIn(BaseModel):
    target_fpr: float = Field(gt=0, lt=1)
    population: str = Field(min_length=10, max_length=4000)


@router.post("/benchmarks/runs/{run_id}/calibration-profiles", status_code=201)
def calibration_profile(
    run_id: uuid.UUID,
    body: CalibrationIn,
    p: Principal = Depends(require("admin.models")),
    db: Session = Depends(get_db),
) -> dict:
    prof = bench.create_calibration_profile(db, p.user, p.org_id, _run(db, run_id), body.target_fpr, body.population)
    db.commit()
    return _profile_dict(prof)


def _profile_dict(prof: CalibrationProfile) -> dict:
    return {
        "id": str(prof.id),
        "method_id": prof.method_id,
        "method_version": prof.method_version,
        "calibration_method": prof.calibration_method,
        "parameters": prof.parameters,
        "threshold": prof.threshold,
        "target_fpr": prof.target_fpr,
        "population": prof.population,
        "benchmark_run_id": str(prof.benchmark_run_id),
        "metrics": prof.metrics,
        "validated": prof.validated,
        "created_at": prof.created_at,
    }


@router.get("/benchmarks/calibration-profiles")
def calibration_profiles(
    p: Principal = Depends(require("benchmark.read")), db: Session = Depends(get_db)
) -> list[dict]:
    return [
        _profile_dict(x)
        for x in db.execute(select(CalibrationProfile).order_by(CalibrationProfile.created_at.desc())).scalars()
    ]


@router.get("/benchmarks/runs/{run_id}/samples")
def run_samples(
    run_id: uuid.UUID,
    p: Principal = Depends(require("benchmark.read")),
    db: Session = Depends(get_db),
    limit: int = Query(500, ge=1, le=5000),
) -> list[dict]:
    _run(db, run_id)
    rows = db.execute(select(BenchmarkSample).where(BenchmarkSample.run_id == run_id).limit(limit)).scalars()
    return [
        {
            "sample_key": s.sample_key,
            "split": s.split,
            "label": s.label,
            "group": s.group,
            "transform": s.transform,
            "score": s.score,
            "status": s.status,
        }
        for s in rows
    ]
