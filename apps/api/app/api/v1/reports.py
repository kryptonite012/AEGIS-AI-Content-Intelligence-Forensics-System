from __future__ import annotations

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.errors import conflict, not_found
from app.db import get_db
from app.models import Report
from app.schemas.common import ORM
from app.security.deps import Principal, require
from app.services import investigations as cases
from app.services import reports as svc
from app.storage.base import get_storage

router = APIRouter(tags=["reports"])


class ReportOut(ORM):
    id: uuid.UUID
    investigation_id: uuid.UUID
    version: int
    status: str
    supersedes_id: uuid.UUID | None
    correction_reason: str | None
    schema_version: str
    json_sha256: str
    pdf_sha256: str | None
    generated_at: datetime
    finalized_at: datetime | None


def _report(db: Session, p: Principal, report_id: uuid.UUID) -> Report:
    rep = db.get(Report, report_id)
    if rep is None:
        raise not_found("report")
    cases.get_case(db, p, rep.investigation_id)
    return rep


@router.get("/investigations/{case_id}/reports", response_model=list[ReportOut])
def list_reports(case_id: uuid.UUID, p: Principal = Depends(require("report.read")), db: Session = Depends(get_db)):
    cases.get_case(db, p, case_id)
    return db.execute(select(Report).where(Report.investigation_id == case_id).order_by(Report.version)).scalars().all()


@router.get("/reports", response_model=list[ReportOut])
def all_reports(p: Principal = Depends(require("report.read")), db: Session = Depends(get_db)):
    visible = cases.visible_cases(p).with_only_columns(cases.Investigation.id)
    return (
        db.execute(
            select(Report).where(Report.investigation_id.in_(visible)).order_by(Report.generated_at.desc()).limit(200)
        )
        .scalars()
        .all()
    )


@router.post("/investigations/{case_id}/reports", response_model=ReportOut, status_code=201)
def generate(case_id: uuid.UUID, p: Principal = Depends(require("report.generate")), db: Session = Depends(get_db)):
    inv = cases.get_case(db, p, case_id, for_update=True)
    rep = svc.generate(db, p, inv)
    db.commit()
    db.refresh(rep)
    return rep


class CorrectionIn(BaseModel):
    reason: str = Field(min_length=10, max_length=4000)


@router.post("/reports/{report_id}/corrections", response_model=ReportOut, status_code=201)
def correction(
    report_id: uuid.UUID,
    body: CorrectionIn,
    p: Principal = Depends(require("report.generate")),
    db: Session = Depends(get_db),
):
    old = _report(db, p, report_id)
    if old.status != "final":
        raise conflict("Only finalised reports are corrected; regenerate the draft instead.")
    inv = cases.get_case(db, p, old.investigation_id, for_update=True)
    rep = svc.generate(db, p, inv, correction_of=old, correction_reason=body.reason)
    db.commit()
    db.refresh(rep)
    return rep


@router.post("/reports/{report_id}/finalize", response_model=ReportOut)
def finalize(report_id: uuid.UUID, p: Principal = Depends(require("report.finalize")), db: Session = Depends(get_db)):
    rep = _report(db, p, report_id)
    inv = cases.get_case(db, p, rep.investigation_id, for_update=True)
    svc.finalize(db, p, inv, rep)
    db.commit()
    db.refresh(rep)
    return rep


@router.get("/reports/{report_id}/json")
def report_json(
    report_id: uuid.UUID, p: Principal = Depends(require("report.read")), db: Session = Depends(get_db)
) -> Response:
    rep = _report(db, p, report_id)
    audit.record(
        db,
        "report.exported",
        "report",
        rep.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=rep.investigation_id,
        ip=p.ip,
        details={"format": "json"},
    )
    db.commit()
    body = json.dumps(
        {
            "payload": rep.payload,
            "manifest": {
                "schema": rep.schema_version,
                "json_sha256": rep.json_sha256,
                "pdf_sha256": rep.pdf_sha256,
                "canonicalisation": "JSON, sorted keys, no whitespace",
            },
        },
        indent=2,
        default=str,
    )
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="aegis-report-{rep.id}-v{rep.version}.json"'},
    )


@router.get("/reports/{report_id}/pdf")
def report_pdf(
    report_id: uuid.UUID, p: Principal = Depends(require("report.read")), db: Session = Depends(get_db)
) -> StreamingResponse:
    rep = _report(db, p, report_id)
    if not rep.pdf_storage_key:
        raise not_found("pdf")
    audit.record(
        db,
        "report.exported",
        "report",
        rep.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=rep.investigation_id,
        ip=p.ip,
        details={"format": "pdf"},
    )
    db.commit()
    return StreamingResponse(
        get_storage().open(rep.pdf_storage_key),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="aegis-report-{rep.id}-v{rep.version}.pdf"',
            "X-AEGIS-SHA256": rep.pdf_sha256 or "",
        },
    )


@router.post("/reports/{report_id}/verify")
def verify(report_id: uuid.UUID, p: Principal = Depends(require("report.read")), db: Session = Depends(get_db)) -> dict:
    rep = _report(db, p, report_id)
    result = svc.verify(rep)
    audit.record(
        db,
        "report.verified",
        "report",
        rep.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=rep.investigation_id,
        ip=p.ip,
        details=result,
    )
    db.commit()
    return result
