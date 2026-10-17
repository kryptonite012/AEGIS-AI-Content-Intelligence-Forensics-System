from __future__ import annotations

import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.config import get_settings
from app.core.errors import AppError, bad_request, conflict, not_found
from app.core.ratelimit import check as rate_check
from app.db import get_db
from app.models import (
    AnalysisArtifact,
    AnalysisJob,
    DetectorRun,
    EvidenceItem,
    EvidenceVersion,
    UploadSession,
)
from app.schemas.common import ORM, UserRef
from app.security.deps import Principal, require
from app.services import evidence as ev
from app.services import investigations as cases
from app.storage.base import get_storage

router = APIRouter(tags=["evidence"])


class VersionOut(ORM):
    id: uuid.UUID
    version_no: int
    kind: str
    parent_version_id: uuid.UUID | None
    sha256: str
    size_bytes: int
    mime_type: str
    original_filename: str | None
    transformations: list[str]
    metadata_status: dict[str, Any]
    scan_status: str
    reason: str | None
    created_at: datetime
    purged_at: datetime | None


class EvidenceOut(ORM):
    id: uuid.UUID
    investigation_id: uuid.UUID
    display_name: str
    role: str
    modality: str
    mime_type: str
    status: str
    description: str | None
    acquired_at: datetime
    uploaded_by: UserRef
    is_demo_fixture: bool
    extraction: dict[str, Any] | None
    versions: list[VersionOut]


def _tmpdir() -> Path:
    d = Path(get_settings().storage_root).parent / "tmp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get_item(db: Session, p: Principal, evidence_id: uuid.UUID) -> EvidenceItem:
    item = db.get(EvidenceItem, evidence_id)
    if item is None or item.organization_id != p.org_id:
        raise not_found("evidence")
    cases.get_case(db, p, item.investigation_id)  # classification visibility
    return item


@router.post("/investigations/{case_id}/evidence", response_model=EvidenceOut, status_code=201)
def upload_evidence(
    case_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    role: Literal["primary", "process_evidence"] = Form("primary"),
    description: str | None = Form(None, max_length=4000),
    p: Principal = Depends(require("evidence.upload")),
    db: Session = Depends(get_db),
) -> EvidenceItem:
    s = get_settings()
    rate_check("upload", str(p.user.id), s.upload_rate_limit_per_hour, 3600)
    inv = cases.get_case(db, p, case_id, for_update=True)
    with tempfile.TemporaryDirectory(dir=_tmpdir()) as td:
        path = Path(td) / "upload.bin"
        ev.copy_upload_to_temp(file.file, path, s.max_upload_mb * 1024 * 1024)
        item = ev.ingest(db, p, inv, path, file.filename or "evidence", role=role, description=description)
        db.commit()
    db.refresh(item)
    return item


class UploadInit(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    total_size: int = Field(gt=0)
    role: Literal["primary", "process_evidence"] = "primary"


@router.post("/investigations/{case_id}/uploads", status_code=201)
def init_chunked_upload(
    case_id: uuid.UUID,
    body: UploadInit,
    p: Principal = Depends(require("evidence.upload")),
    db: Session = Depends(get_db),
) -> dict:
    s = get_settings()
    if body.total_size > s.max_upload_mb * 1024 * 1024:
        raise AppError(413, "payload_too_large", f"Upload exceeds the {s.max_upload_mb} MB limit.")
    inv = cases.get_case(db, p, case_id)
    cases.ensure_unlocked(inv)
    us = UploadSession(
        investigation_id=inv.id, user_id=p.user.id, filename=body.filename, role=body.role, total_size=body.total_size
    )
    db.add(us)
    db.commit()
    return {"upload_id": str(us.id), "chunk_size": s.upload_chunk_mb * 1024 * 1024, "received": 0}


def _session(db: Session, p: Principal, upload_id: uuid.UUID) -> UploadSession:
    us = db.get(UploadSession, upload_id)
    if us is None or us.user_id != p.user.id or us.status != "open":
        raise not_found("upload session")
    return us


@router.put("/uploads/{upload_id}")
async def put_chunk(
    upload_id: uuid.UUID,
    request: Request,
    offset: int = Query(ge=0),
    p: Principal = Depends(require("evidence.upload")),
    db: Session = Depends(get_db),
) -> dict:
    us = _session(db, p, upload_id)
    if offset != us.received:
        raise conflict("Offset does not match bytes received.", {"received": us.received})
    limit = get_settings().upload_chunk_mb * 1024 * 1024
    data = b""
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            raise AppError(413, "payload_too_large", "Chunk exceeds the configured chunk size.")
    if us.received + len(data) > us.total_size:
        raise bad_request("Chunk exceeds the declared total size.")
    part = _tmpdir() / f"upload-{us.id}.part"
    with part.open("ab") as f:
        f.write(data)
    us.received += len(data)
    db.commit()
    return {"upload_id": str(us.id), "received": us.received, "total_size": us.total_size}


@router.post("/uploads/{upload_id}/complete", response_model=EvidenceOut, status_code=201)
def complete_chunked_upload(
    upload_id: uuid.UUID, p: Principal = Depends(require("evidence.upload")), db: Session = Depends(get_db)
) -> EvidenceItem:
    us = _session(db, p, upload_id)
    if us.received != us.total_size:
        raise conflict("Upload incomplete.", {"received": us.received, "total_size": us.total_size})
    inv = cases.get_case(db, p, us.investigation_id, for_update=True)
    part = _tmpdir() / f"upload-{us.id}.part"
    try:
        item = ev.ingest(db, p, inv, part, us.filename, role=us.role)
        us.status = "completed"
        db.commit()
    finally:
        part.unlink(missing_ok=True)
    db.refresh(item)
    return item


@router.get("/investigations/{case_id}/evidence", response_model=list[EvidenceOut])
def list_case_evidence(
    case_id: uuid.UUID, p: Principal = Depends(require("evidence.read")), db: Session = Depends(get_db)
):
    cases.get_case(db, p, case_id)
    return (
        db.execute(
            select(EvidenceItem).where(EvidenceItem.investigation_id == case_id).order_by(EvidenceItem.acquired_at)
        )
        .scalars()
        .all()
    )


@router.get("/evidence")
def list_evidence(
    p: Principal = Depends(require("evidence.read")),
    db: Session = Depends(get_db),
    modality: str | None = None,
    q: str | None = Query(None, max_length=200),
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    """Evidence across visible cases, with the latest analysis job for each item (used by modality views)."""
    visible = cases.visible_cases(p).with_only_columns(cases.Investigation.id)
    qry = select(EvidenceItem).where(EvidenceItem.investigation_id.in_(visible))
    if modality:
        mods = modality.split(",")
        qry = qry.where(EvidenceItem.modality.in_(mods))
    if q:
        qry = qry.where(
            EvidenceItem.display_name.ilike(f"%{q}%")
            | EvidenceItem.id.in_(
                select(EvidenceVersion.evidence_item_id).where(EvidenceVersion.sha256.startswith(q.lower()))
            )
        )
    items = db.execute(qry.order_by(EvidenceItem.acquired_at.desc()).limit(limit)).scalars().all()
    out = []
    for it in items:
        job = db.execute(
            select(AnalysisJob)
            .where(AnalysisJob.evidence_item_id == it.id)
            .order_by(AnalysisJob.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        original = next((v for v in it.versions if v.kind == "original"), None)
        out.append(
            {
                "id": str(it.id),
                "investigation_id": str(it.investigation_id),
                "display_name": it.display_name,
                "modality": it.modality,
                "mime_type": it.mime_type,
                "status": it.status,
                "role": it.role,
                "acquired_at": it.acquired_at,
                "sha256": original.sha256 if original else None,
                "size_bytes": original.size_bytes if original else None,
                "is_demo_fixture": it.is_demo_fixture,
                "latest_job": None
                if job is None
                else {
                    "id": str(job.id),
                    "status": job.status,
                    "profile": job.profile_id,
                    "primary_outcome": (job.fusion or {}).get("primary_outcome"),
                    "primary_label": (job.fusion or {}).get("primary_label"),
                    "created_at": job.created_at,
                },
            }
        )
    return out


@router.get("/evidence/{evidence_id}", response_model=EvidenceOut)
def get_evidence(
    evidence_id: uuid.UUID, p: Principal = Depends(require("evidence.read")), db: Session = Depends(get_db)
) -> EvidenceItem:
    return _get_item(db, p, evidence_id)


@router.get("/evidence/{evidence_id}/versions/{version_id}/download")
def download_version(
    evidence_id: uuid.UUID,
    version_id: uuid.UUID,
    p: Principal = Depends(require("evidence.download")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    item = _get_item(db, p, evidence_id)
    v = next((x for x in item.versions if x.id == version_id), None)
    if v is None:
        raise not_found("version")
    if v.purged_at:
        raise AppError(410, "purged", "This version's bytes were purged under the retention policy.")
    audit.record(
        db,
        "evidence.downloaded",
        "evidence_version",
        v.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=item.investigation_id,
        ip=p.ip,
        details={"sha256": v.sha256, "kind": v.kind},
    )
    db.commit()
    name = (v.original_filename or item.display_name).replace('"', "")
    return StreamingResponse(
        get_storage().open(v.storage_key),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-AEGIS-SHA256": v.sha256},
    )


@router.get("/evidence/{evidence_id}/thumbnail")
def thumbnail(
    evidence_id: uuid.UUID, p: Principal = Depends(require("evidence.read")), db: Session = Depends(get_db)
) -> Response:
    item = _get_item(db, p, evidence_id)
    v = next((x for x in item.versions if x.kind == "thumbnail" and not x.purged_at), None)
    if v is None:
        raise not_found("thumbnail")
    data = b"".join(get_storage().open(v.storage_key))
    return Response(data, media_type="image/png", headers={"Cache-Control": "private, max-age=300"})


@router.get("/evidence/{evidence_id}/text")
def extracted_text(
    evidence_id: uuid.UUID,
    p: Principal = Depends(require("evidence.read")),
    db: Session = Depends(get_db),
    version: Literal["normalized", "redacted"] = "normalized",
) -> dict:
    item = _get_item(db, p, evidence_id)
    kind = "normalized_text" if version == "normalized" else "redacted"
    v = next((x for x in reversed(item.versions) if x.kind == kind and not x.purged_at), None)
    if v is None:
        raise not_found("text version")
    with get_storage().local_path(v.storage_key) as path:
        text = path.read_text("utf-8")
    return {
        "version_id": str(v.id),
        "kind": v.kind,
        "sha256": v.sha256,
        "text": text,
        "extraction": item.extraction,
        "note": "Untrusted content; displayed as data only.",
    }


@router.post("/evidence/{evidence_id}/verify")
def verify(
    evidence_id: uuid.UUID, p: Principal = Depends(require("evidence.verify")), db: Session = Depends(get_db)
) -> dict:
    item = _get_item(db, p, evidence_id)
    result = ev.verify_integrity(db, p, item)
    db.commit()
    return result


class RedactIn(BaseModel):
    spans: list[tuple[int, int]] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=5, max_length=2000)


@router.post("/evidence/{evidence_id}/redactions", response_model=VersionOut, status_code=201)
def redact(
    evidence_id: uuid.UUID,
    body: RedactIn,
    p: Principal = Depends(require("evidence.redact")),
    db: Session = Depends(get_db),
) -> EvidenceVersion:
    item = _get_item(db, p, evidence_id)
    v = ev.redact_text(db, p, item, body.spans, body.reason)
    db.commit()
    db.refresh(v)
    return v


@router.get("/artifacts/{artifact_id}")
def get_artifact(
    artifact_id: uuid.UUID, p: Principal = Depends(require("analysis.read")), db: Session = Depends(get_db)
) -> Response:
    a = db.get(AnalysisArtifact, artifact_id)
    if a is None:
        raise not_found("artifact")
    run = db.get(DetectorRun, a.detector_run_id)
    job = db.get(AnalysisJob, run.job_id) if run else None
    if job is None or job.organization_id != p.org_id:
        raise not_found("artifact")
    cases.get_case(db, p, job.investigation_id)
    data = b"".join(get_storage().open(a.storage_key))
    return Response(
        data, media_type=a.media_type, headers={"Cache-Control": "private, max-age=3600", "X-AEGIS-SHA256": a.sha256}
    )
