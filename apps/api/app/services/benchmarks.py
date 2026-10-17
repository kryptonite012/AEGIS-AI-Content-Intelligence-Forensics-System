"""Benchmark Laboratory: dataset registration, reproducible runs, calibration profiles.

Result kinds are kept separate: ``locally_measured`` (a real method on registered real data),
``simulated`` (a real method on synthetic data, or a synthetic model), and the record-only kinds
``published`` / ``reproduced`` / ``vendor_reported`` which store cited numbers without claiming
AEGIS measured them.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import platform
import secrets
import sys
import uuid
from dataclasses import asdict
from typing import Any

import numpy as np
from aegis_ml.core import AnalysisInput, Modality
from aegis_ml.text.extract import MIN_TOKENS_FOR_ANALYSIS
from aegis_ml.text.language import identify_language
from aegis_ml.text.reference_watermark import ReferenceWatermarkVerifier, generate_reference_text
from aegis_ml.text.tokenize import count_tokens
from aegis_research import __version__ as research_version
from aegis_research import reliability as rel
from aegis_research.watermark import replace_tokens
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.errors import AppError, bad_request, conflict
from app.db import get_sessionmaker, utcnow
from app.models import BenchmarkRun, BenchmarkSample, CalibrationProfile, Dataset, User
from app.services.analysis import jsonable, registry
from app.storage.base import ObjectExists, get_storage

MAX_DATASET_SAMPLES = 50_000
SPLITS = {"train", "validation", "test"}


def _norm_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()


def parse_dataset(raw: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for n, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError as exc:
            raise bad_request(f"Line {n}: invalid JSON.") from exc
        if not isinstance(r, dict) or not isinstance(r.get("text"), str) or r.get("label") not in (0, 1):
            raise bad_request(f"Line {n}: each record needs 'text' (string) and 'label' (0=human, 1=AI).")
        split = r.get("split", "test")
        if split not in SPLITS:
            raise bad_request(f"Line {n}: split must be one of {sorted(SPLITS)}.")
        rows.append(
            {
                "id": str(r.get("id", n))[:120],
                "text": r["text"],
                "label": int(r["label"]),
                "split": split,
                "group": str(r["group"])[:80] if r.get("group") is not None else None,
                "generator": r.get("generator"),
                "domain": r.get("domain"),
                "language": r.get("language"),
                "transform": str(r.get("transform", "original"))[:60],
            }
        )
        if len(rows) > MAX_DATASET_SAMPLES:
            raise bad_request(f"Datasets are limited to {MAX_DATASET_SAMPLES} samples.")
    if not rows:
        raise bad_request("Dataset is empty.")
    ids = [r["id"] for r in rows]
    if len(set(zip(ids, (r["transform"] for r in rows), strict=True))) != len(rows):
        raise bad_request("Sample ids must be unique per transform.")
    by_hash: dict[str, set[str]] = {}
    for r in rows:
        by_hash.setdefault(_norm_hash(r["text"]), set()).add(r["split"])
    cross = [h for h, s in by_hash.items() if len(s) > 1]
    dup_report = {
        "distinct_texts": len(by_hash),
        "cross_split_duplicates": len(cross),
        "within_dataset_duplicates": len(rows) - len(by_hash),
    }
    return rows, dup_report


def register_dataset(db: Session, user: User, raw: bytes, meta: dict[str, Any], org_id: uuid.UUID | None) -> Dataset:
    rows, dup = parse_dataset(raw)
    for f in ("name", "version", "provenance", "license", "consent_basis"):
        if not str(meta.get(f, "")).strip():
            raise bad_request(f"Dataset field '{f}' is required (provenance, licence and consent must be documented).")
    sha = hashlib.sha256(raw).hexdigest()
    key = f"datasets/{sha[:2]}/{sha}.jsonl"
    try:
        get_storage().put_bytes(key, raw, "application/x-ndjson")
    except ObjectExists:
        pass
    splits: dict[str, int] = {}
    for r in rows:
        splits[r["split"]] = splits.get(r["split"], 0) + 1
    ds = Dataset(
        name=meta["name"],
        version=meta["version"],
        modality="text",
        provenance=meta["provenance"],
        license=meta["license"],
        consent_basis=meta["consent_basis"],
        documentation=meta.get("documentation", ""),
        is_synthetic=bool(meta.get("is_synthetic")),
        sha256=sha,
        storage_key=key,
        n_samples=len(rows),
        splits=splits,
        fields=sorted({k for r in rows for k, v in r.items() if v is not None}),
        duplicate_report=dup,
        created_by_id=user.id,
    )
    db.add(ds)
    db.flush()
    audit.record(
        db,
        "dataset.registered",
        "dataset",
        ds.id,
        actor=user,
        organization_id=org_id,
        details={"name": ds.name, "version": ds.version, "sha256": sha, "n": ds.n_samples, **dup},
    )
    return ds


def load_rows(ds: Dataset) -> list[dict[str, Any]]:
    raw = b"".join(get_storage().open(ds.storage_key))
    if hashlib.sha256(raw).hexdigest() != ds.sha256:
        raise AppError(409, "dataset_integrity", "Stored dataset no longer matches its recorded hash.")
    return parse_dataset(raw)[0]


def create_run(
    db: Session, user: User, org_id: uuid.UUID | None, method_id: str, dataset: Dataset, config: dict[str, Any]
) -> BenchmarkRun:
    m = registry().get(method_id)
    if m is None:
        raise bad_request(f"Unknown method {method_id}.")
    if Modality.TEXT not in m.info.modalities:
        raise bad_request("Dataset benchmarks currently support text methods only.")
    run = BenchmarkRun(
        dataset_id=dataset.id,
        method_id=method_id,
        method_version=m.info.version,
        result_kind="simulated" if dataset.is_synthetic else "locally_measured",
        status="queued",
        seed=int(config.get("seed", 0)),
        config=jsonable(config),
        created_by_id=user.id,
    )
    db.add(run)
    db.flush()
    audit.record(
        db,
        "benchmark.queued",
        "benchmark_run",
        run.id,
        actor=user,
        organization_id=org_id,
        details={"method_id": method_id, "dataset": f"{dataset.name}@{dataset.version}", "config": run.config},
    )
    return run


def _pick_threshold(val: list[tuple[int, float]], target_fpr: float) -> float | None:
    if not val or len({y for y, _ in val}) < 2:
        return None
    op = rel.tpr_at_fpr([y for y, _ in val], [s for _, s in val], target_fpr)
    return op.threshold


def _metrics(labels: list[int], scores: list[float], threshold: float | None, groups: list[str] | None) -> dict:
    if len(set(labels)) < 2:
        return {"error": "Both classes are required to compute metrics.", "n": len(labels)}
    if threshold is None:
        return {
            "n": len(labels),
            "auroc": rel.auroc(labels, scores),
            "roc": rel.roc_curve(labels, scores),
            "pr": rel.pr_curve(labels, scores),
            "operating_points": [asdict(rel.tpr_at_fpr(labels, scores, f)) for f in (0.01, 0.001)],
            "note": "No threshold: threshold-dependent metrics omitted.",
        }
    return rel.evaluate_scores(labels, scores, threshold, groups=groups)


def execute_benchmark(run_id: uuid.UUID | str, method_override=None) -> str:  # type: ignore[no-untyped-def]
    run_id = uuid.UUID(str(run_id))
    with get_sessionmaker()() as db:
        run = db.get(BenchmarkRun, run_id)
        if run is None or run.status in ("completed", "failed"):
            return run.status if run else "missing"
        run.status = "running"
        db.commit()
        try:
            ds = db.get(Dataset, run.dataset_id)
            assert ds is not None
            rows = load_rows(ds)
            cfg = run.config or {}
            hold = cfg.get("holdout") or {}
            eval_split = cfg.get("split", "test")
            dup_hashes = {h for h, splits in _hash_splits(rows).items() if len(splits) > 1}
            method = method_override or registry()[run.method_id]
            ok, reason = method.availability()
            if not ok:
                raise AppError(409, "method_unavailable", f"{run.method_id} is unavailable: {reason}")
            scored: dict[str, list[tuple[dict, float | None, str]]] = {"validation": [], eval_split: []}
            excluded = 0
            for r in rows:
                if r["split"] not in scored:
                    continue
                if _norm_hash(r["text"]) in dup_hashes:
                    excluded += 1
                    continue
                if hold and r["split"] == eval_split and r.get(hold.get("field")) not in hold.get("values", []):
                    continue
                if hold and r["split"] == "validation" and r.get(hold.get("field")) in hold.get("values", []):
                    continue
                toks = count_tokens(r["text"])
                lang = r.get("language") or identify_language(r["text"]).get("code")
                res = method.run(
                    AnalysisInput(
                        Modality.TEXT,
                        "text/plain",
                        path_placeholder(),
                        "0" * 64,
                        text=r["text"],
                        language=lang,
                        extraction={"token_count": toks},
                    )
                )
                scored[r["split"]].append((r, res.score if str(res.status) == "completed" else None, str(res.status)))
            for split, items in scored.items():
                for r, score, status in items:
                    db.add(
                        BenchmarkSample(
                            run_id=run.id,
                            sample_key=r["id"],
                            split=split,
                            label=r["label"],
                            group=r["group"],
                            transform=r["transform"],
                            score=score,
                            status=status,
                        )
                    )
            val = [
                (r["label"], s) for r, s, _ in scored["validation"] if s is not None and r["transform"] == "original"
            ]
            threshold = cfg.get("threshold")
            threshold_source = "configured" if threshold is not None else None
            if threshold is None:
                threshold = _pick_threshold(val, float(cfg.get("target_fpr", 0.01)))
                threshold_source = "validation_split" if threshold is not None else "none"
            test = [(r, s) for r, s, _ in scored[eval_split] if s is not None]
            not_scored = sum(1 for _, s, _ in scored[eval_split] if s is None)
            orig = [(r, s) for r, s in test if r["transform"] == "original"]
            metrics: dict[str, Any] = {
                "overall": _metrics(
                    [r["label"] for r, _ in orig],
                    [s for _, s in orig],
                    threshold,
                    [r["group"] or "unspecified" for r, _ in orig],
                ),
                "threshold": threshold,
                "threshold_source": threshold_source,
                "evaluated_split": eval_split,
                "not_scored": not_scored,
                "excluded_cross_split_duplicates": excluded,
                "short_text_fraction": float(
                    np.mean([count_tokens(r["text"]) < MIN_TOKENS_FOR_ANALYSIS for r, _ in orig])
                )
                if orig
                else None,
            }
            transforms = sorted({r["transform"] for r, _ in test} - {"original"})
            metrics["robustness"] = {
                t: _metrics(
                    [r["label"] for r, s in test if r["transform"] == t],
                    [s for r, s in test if r["transform"] == t],
                    threshold,
                    None,
                )
                for t in transforms
            }
            run.metrics = jsonable(metrics)
            run.manifest = jsonable(
                {
                    "dataset": {
                        "id": str(ds.id),
                        "name": ds.name,
                        "version": ds.version,
                        "sha256": ds.sha256,
                        "synthetic": ds.is_synthetic,
                        "license": ds.license,
                    },
                    "method": {"id": run.method_id, "version": run.method_version},
                    "config": cfg,
                    "seed": run.seed,
                    "holdout": hold or None,
                    "environment": {
                        "python": sys.version.split()[0],
                        "platform": platform.platform(),
                        "aegis_research": research_version,
                        "numpy": np.__version__,
                    },
                    "result_kind": run.result_kind,
                    "started": str(run.created_at),
                    "finished": utcnow().isoformat(),
                    "samples_scored": sum(len(v) for v in scored.values()),
                }
            )
            run.status, run.finished_at = "completed", utcnow()
            audit.record(
                db,
                "benchmark.completed",
                "benchmark_run",
                run.id,
                actor_label="system:worker",
                details={
                    "method_id": run.method_id,
                    "result_kind": run.result_kind,
                    "auroc": metrics["overall"].get("auroc"),
                },
            )
            db.commit()
            return "completed"
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            run = db.get(BenchmarkRun, run_id)
            assert run is not None
            run.status, run.error, run.finished_at = "failed", f"{type(exc).__name__}: {str(exc)[:500]}", utcnow()
            db.commit()
            return "failed"


def path_placeholder():  # type: ignore[no-untyped-def]
    from pathlib import Path

    return Path("/dev/null")


def _hash_splits(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for r in rows:
        out.setdefault(_norm_hash(r["text"]), set()).add(r["split"])
    return out


def build_reference_watermark_suite(n_per_class: int = 120, seed: int = 2024) -> tuple[bytes, bytes]:
    """Synthetic, clearly labelled dataset for the reference watermark verifier. Returns (jsonl, key)."""
    key = secrets.token_bytes(32)
    rng = np.random.default_rng(seed)
    lines = []
    for i in range(n_per_class * 2):
        label = int(i % 2 == 0)
        split = "validation" if i < n_per_class // 2 else "test"
        length = int(rng.choice([20, 40, 80, 160]))
        text = generate_reference_text(key, length, seed=seed + i, watermarked=bool(label))
        base = {"id": f"s{i}", "label": label, "split": split, "group": f"length_{length}", "language": "synthetic"}
        lines.append(json.dumps({**base, "text": text, "transform": "original"}))
        if split == "test":
            from aegis_ml.text.reference_watermark import VOCAB, token_ids

            for frac in (0.2, 0.4):
                ids = replace_tokens(token_ids(text), frac, len(VOCAB), rng)
                lines.append(
                    json.dumps(
                        {
                            **base,
                            "text": " ".join(VOCAB[t] for t in ids),
                            "transform": f"token_replacement_{int(frac * 100)}pct",
                        }
                    )
                )
    return "\n".join(lines).encode(), key


def run_reference_watermark_benchmark(db: Session, user: User, org_id: uuid.UUID | None) -> BenchmarkRun:
    raw, key = build_reference_watermark_suite()
    sha = hashlib.sha256(raw).hexdigest()
    existing = db.execute(select(Dataset).where(Dataset.sha256 == sha)).scalar_one_or_none()
    version = f"seed2024-{sha[:8]}"
    ds = existing or register_dataset(
        db,
        user,
        raw,
        {
            "name": "aegis-reference-watermark-synthetic",
            "version": version,
            "provenance": "Generated by AEGIS SyntheticLM with a per-run random key (key not stored).",
            "license": "CC0-1.0 (synthetic)",
            "consent_basis": "Not applicable: no human-authored content.",
            "documentation": "Pseudo-word text with/without the AEGIS reference watermark; test split includes "
            "20% and 40% random token replacement. SIMULATION ONLY.",
            "is_synthetic": True,
        },
        org_id,
    )
    run = create_run(
        db,
        user,
        org_id,
        "watermark.aegis_reference_text",
        ds,
        {
            "split": "test",
            "target_fpr": 0.01,
            "seed": 2024,
            "key_fingerprint": hashlib.sha256(b"aegis-wm-fp:" + key).hexdigest()[:16],
        },
    )
    db.commit()
    execute_benchmark(run.id, method_override=ReferenceWatermarkVerifier(key=key))
    db.refresh(run)
    return run


def import_scores(
    db: Session, user: User, org_id: uuid.UUID | None, name: str, raw: bytes, kind: str, citation: str | None
) -> BenchmarkRun:
    if kind not in ("locally_measured", "vendor_reported", "published", "reproduced"):
        raise bad_request("Invalid result kind for imported scores.")
    if kind in ("published", "vendor_reported", "reproduced") and not citation:
        raise bad_request("A citation or source is required for published, reproduced or vendor-reported results.")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    labels, scores, groups, transforms = [], [], [], []
    for n, row in enumerate(reader, 2):
        try:
            labels.append(int(row["label"]))
            scores.append(float(row["score"]))
        except (KeyError, ValueError) as exc:
            raise bad_request(f"Row {n}: 'label' (0/1) and numeric 'score' columns are required.") from exc
        groups.append(row.get("group") or "unspecified")
        transforms.append(row.get("transform") or "original")
    if len(labels) < 2 or not set(labels) <= {0, 1}:
        raise bad_request("At least two rows with labels 0/1 are required.")
    threshold = None
    orig = [i for i, t in enumerate(transforms) if t == "original"]
    metrics = {
        "overall": _metrics([labels[i] for i in orig], [scores[i] for i in orig], threshold, None),
        "threshold": None,
        "threshold_source": "none",
        "note": "Imported scores: AEGIS computed metrics from the supplied labels and scores; it did not "
        "run the detector.",
    }
    run = BenchmarkRun(
        method_id=f"imported:{name[:60]}",
        method_version="n/a",
        result_kind=kind,
        status="completed",
        config={"source": "imported_scores", "rows": len(labels)},
        metrics=jsonable(metrics),
        manifest={"sha256": hashlib.sha256(raw).hexdigest(), "rows": len(labels)},
        source_citation=citation,
        created_by_id=user.id,
        finished_at=utcnow(),
    )
    db.add(run)
    db.flush()
    for i in range(len(labels)):
        db.add(
            BenchmarkSample(
                run_id=run.id,
                sample_key=str(i),
                split="test",
                label=labels[i],
                group=groups[i],
                transform=transforms[i],
                score=scores[i],
                status="completed",
            )
        )
    audit.record(
        db,
        "benchmark.scores_imported",
        "benchmark_run",
        run.id,
        actor=user,
        organization_id=org_id,
        details={"name": name, "kind": kind, "rows": len(labels)},
    )
    return run


def create_calibration_profile(
    db: Session, user: User, org_id: uuid.UUID | None, run: BenchmarkRun, target_fpr: float, population: str
) -> CalibrationProfile:
    if run.status != "completed":
        raise conflict("Benchmark run is not complete.")
    samples = (
        db.execute(
            select(BenchmarkSample).where(
                BenchmarkSample.run_id == run.id,
                BenchmarkSample.split == "validation",
                BenchmarkSample.transform == "original",
                BenchmarkSample.score.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    if len({s.label for s in samples}) < 2:
        raise conflict("Calibration requires a labelled validation split distinct from the test split.")
    y = [s.label for s in samples]
    sc = [float(s.score) for s in samples]  # type: ignore[arg-type]
    cal = rel.PlattCalibrator.fit(y, sc)
    op = rel.tpr_at_fpr(y, sc, target_fpr)
    validated = run.result_kind == "locally_measured" and op.estimable
    prof = CalibrationProfile(
        method_id=run.method_id,
        method_version=run.method_version,
        calibration_method="platt",
        parameters={"a": cal.a, "b": cal.b},
        threshold=op.threshold,
        target_fpr=target_fpr,
        population=population,
        languages=[],
        benchmark_run_id=run.id,
        metrics=jsonable({"validation_n": len(y), "operating_point": asdict(op)}),
        validated=validated,
        created_by_id=user.id,
    )
    db.add(prof)
    db.flush()
    audit.record(
        db,
        "calibration.created",
        "calibration_profile",
        prof.id,
        actor=user,
        organization_id=org_id,
        details={
            "run_id": str(run.id),
            "target_fpr": target_fpr,
            "validated": validated,
            "threshold": op.threshold,
            "reason_not_validated": None
            if validated
            else ("simulated data" if run.result_kind != "locally_measured" else op.note),
        },
    )
    return prof
