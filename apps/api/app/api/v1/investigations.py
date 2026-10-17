from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.v1._util import paginate
from app.audit import service as audit
from app.audit.service import canonical
from app.core.errors import bad_request, conflict, forbidden, not_found
from app.db import get_db, utcnow
from app.models import (
    AnalysisJob,
    Annotation,
    Appeal,
    AuditEvent,
    DeletionRequest,
    EvidenceItem,
    Investigation,
    Membership,
    Report,
    ReviewDecision,
    User,
)
from app.schemas.common import ORM, Page, UserRef
from app.security.deps import Principal, require
from app.security.permissions import role_permissions
from app.services import investigations as cases
from app.services.notifications import notify

router = APIRouter(prefix="/investigations", tags=["investigations"])

Priority = Literal["low", "normal", "high", "urgent"]
MediaCategory = Literal["text", "document", "image", "audio", "video", "mixed"]
Classification = Literal["standard", "restricted"]
Retention = Literal["standard", "extended", "legal_minimum", "research"]


class InvestigationIn(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    case_reference: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9._/-]+$")
    purpose: str = Field(min_length=10, max_length=4000)
    media_category: MediaCategory
    description: str = Field(default="", max_length=20000)
    priority: Priority = "normal"
    assigned_reviewer_id: uuid.UUID | None = None
    legal_basis: str | None = Field(default=None, max_length=4000)
    retention_class: Retention = "standard"
    access_classification: Classification = "standard"
    allow_external_processing: bool = False


class InvestigationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    priority: Priority | None = None
    legal_basis: str | None = Field(default=None, max_length=4000)
    access_classification: Classification | None = None
    retention_class: Retention | None = None
    allow_external_processing: bool | None = None
    pending_questions: list[str] | None = Field(default=None, max_length=50)


class InvestigationOut(ORM):
    id: uuid.UUID
    case_reference: str
    title: str
    purpose: str
    media_category: str
    description: str
    priority: str
    status: str
    legal_basis: str | None
    retention_class: str
    access_classification: str
    legal_hold: bool
    allow_external_processing: bool
    disposition: str | None
    pending_questions: list[str]
    assigned_reviewer: UserRef | None
    created_by: UserRef
    is_demo_fixture: bool
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class InvestigationSummary(ORM):
    id: uuid.UUID
    case_reference: str
    title: str
    media_category: str
    priority: str
    status: str
    access_classification: str
    is_demo_fixture: bool
    assigned_reviewer: UserRef | None
    created_at: datetime
    updated_at: datetime


def _validate_reviewer(db: Session, p: Principal, reviewer_id: uuid.UUID | None) -> None:
    if reviewer_id is None:
        return
    m = db.execute(
        select(Membership).where(Membership.user_id == reviewer_id, Membership.organization_id == p.org_id)
    ).scalar_one_or_none()
    if m is None or "review.decide" not in role_permissions(m.role_id):
        raise bad_request("Assigned reviewer must be an organisation member with review permission.")
    if reviewer_id == p.user.id:
        raise bad_request("Separation of duties: you cannot assign yourself as the reviewer of your own case.")


@router.get("", response_model=Page[InvestigationSummary])
def list_investigations(
    p: Principal = Depends(require("case.read")),
    db: Session = Depends(get_db),
    status: str | None = None,
    priority: str | None = None,
    q: str | None = Query(None, max_length=200),
    assigned_to_me: bool = False,
    sort: Literal["updated_at", "created_at", "priority", "title"] = "updated_at",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
) -> Page[InvestigationSummary]:
    qry = cases.visible_cases(p)
    if status:
        qry = qry.where(Investigation.status.in_(status.split(",")))
    if priority:
        qry = qry.where(Investigation.priority == priority)
    if assigned_to_me:
        qry = qry.where(Investigation.assigned_reviewer_id == p.user.id)
    if q:
        like = f"%{q}%"
        qry = qry.where(or_(Investigation.title.ilike(like), Investigation.case_reference.ilike(like)))
    col = getattr(Investigation, sort)
    qry = qry.order_by(col.asc() if order == "asc" else col.desc())
    items, total = paginate(db, qry, page, page_size)
    return Page(
        items=[InvestigationSummary.model_validate(i) for i in items], total=total, page=page, page_size=page_size
    )


@router.post("", response_model=InvestigationOut, status_code=201)
def create_investigation(
    body: InvestigationIn, p: Principal = Depends(require("case.create")), db: Session = Depends(get_db)
) -> Investigation:
    if db.execute(
        select(Investigation).where(
            Investigation.organization_id == p.org_id, Investigation.case_reference == body.case_reference
        )
    ).first():
        raise conflict("Case reference already exists in this organisation.")
    _validate_reviewer(db, p, body.assigned_reviewer_id)
    inv = Investigation(organization_id=p.org_id, created_by_id=p.user.id, status="draft", **body.model_dump())
    db.add(inv)
    db.flush()
    audit.record(
        db,
        "investigation.created",
        "investigation",
        inv.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        details={
            "case_reference": inv.case_reference,
            "classification": inv.access_classification,
            "external_processing": inv.allow_external_processing,
        },
    )
    if inv.assigned_reviewer_id:
        notify(
            db,
            inv.assigned_reviewer_id,
            p.org_id,
            "assignment",
            f"Assigned as reviewer: {inv.case_reference}",
            inv.title,
            link=f"/cases/{inv.id}",
        )
    db.commit()
    db.refresh(inv)
    return inv


@router.get("/{case_id}", response_model=InvestigationOut)
def get_investigation(
    case_id: uuid.UUID, p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)
) -> Investigation:
    return cases.get_case(db, p, case_id)


@router.patch("/{case_id}", response_model=InvestigationOut)
def update_investigation(
    case_id: uuid.UUID,
    body: InvestigationPatch,
    p: Principal = Depends(require("case.update")),
    db: Session = Depends(get_db),
) -> Investigation:
    inv = cases.get_case(db, p, case_id, for_update=True)
    cases.ensure_unlocked(inv)
    changes = body.model_dump(exclude_unset=True)
    if "allow_external_processing" in changes and changes["allow_external_processing"] and not p.can("admin.settings"):
        raise forbidden("Only administrators can permit external processing for a case.")
    before = {k: getattr(inv, k) for k in changes}
    for k, v in changes.items():
        setattr(inv, k, v)
    audit.record(
        db,
        "investigation.updated",
        "investigation",
        inv.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        details={"before": before, "after": changes},
    )
    db.commit()
    db.refresh(inv)
    return inv


class AssignIn(BaseModel):
    reviewer_id: uuid.UUID | None


@router.post("/{case_id}/assign", response_model=InvestigationOut)
def assign_reviewer(
    case_id: uuid.UUID, body: AssignIn, p: Principal = Depends(require("case.assign")), db: Session = Depends(get_db)
) -> Investigation:
    inv = cases.get_case(db, p, case_id, for_update=True)
    cases.ensure_unlocked(inv)
    _validate_reviewer(db, p, body.reviewer_id)
    if body.reviewer_id and body.reviewer_id == inv.created_by_id:
        raise bad_request("The case creator cannot be its independent reviewer.")
    prev = inv.assigned_reviewer_id
    inv.assigned_reviewer_id = body.reviewer_id
    audit.record(
        db,
        "investigation.reviewer_assigned",
        "investigation",
        inv.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        details={"from": str(prev) if prev else None, "to": str(body.reviewer_id) if body.reviewer_id else None},
    )
    if body.reviewer_id:
        notify(
            db,
            body.reviewer_id,
            p.org_id,
            "assignment",
            f"Assigned as reviewer: {inv.case_reference}",
            inv.title,
            link=f"/cases/{inv.id}",
        )
    db.commit()
    db.refresh(inv)
    return inv


class TransitionIn(BaseModel):
    target: Literal["human_review", "analysis_queued", "inconclusive", "archived"]
    reason: str | None = Field(default=None, max_length=4000)


@router.post("/{case_id}/transition", response_model=InvestigationOut)
def transition(
    case_id: uuid.UUID, body: TransitionIn, p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)
) -> Investigation:
    inv = cases.get_case(db, p, case_id, for_update=True)
    needed = {
        "human_review": "case.update",
        "analysis_queued": "analysis.run",
        "inconclusive": "review.decide",
        "archived": "case.archive",
    }[body.target]
    if inv.status in cases.REOPEN_FROM and body.target == "human_review":
        needed = "case.reopen"
    if not p.can(needed):
        raise forbidden(f"Missing permission: {needed}")
    if body.target == "human_review" and inv.status == "analysis_complete":
        if inv.assigned_reviewer_id is None:
            raise conflict("Assign an independent reviewer before requesting human review.")
        notify(
            db,
            inv.assigned_reviewer_id,
            p.org_id,
            "review_requested",
            f"Review requested: {inv.case_reference}",
            inv.title,
            link=f"/cases/{inv.id}",
        )
    cases.transition(db, inv, body.target, actor=p, reason=body.reason)
    db.commit()
    db.refresh(inv)
    return inv


class LegalHoldIn(BaseModel):
    legal_hold: bool
    reason: str = Field(min_length=5, max_length=2000)


@router.post("/{case_id}/legal-hold", response_model=InvestigationOut)
def legal_hold(
    case_id: uuid.UUID,
    body: LegalHoldIn,
    p: Principal = Depends(require("admin.settings")),
    db: Session = Depends(get_db),
) -> Investigation:
    inv = cases.get_case(db, p, case_id, for_update=True)
    inv.legal_hold = body.legal_hold
    audit.record(
        db,
        "investigation.legal_hold",
        "investigation",
        inv.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        reason=body.reason,
        ip=p.ip,
        details={"legal_hold": body.legal_hold},
    )
    db.commit()
    db.refresh(inv)
    return inv


# ----------------------------------------------------------------------------- annotations


class AnnotationIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    kind: Literal["note", "finding", "question", "contradiction"] = "note"
    evidence_item_id: uuid.UUID | None = None
    detector_run_id: uuid.UUID | None = None


class AnnotationOut(ORM):
    id: uuid.UUID
    kind: str
    body: str
    evidence_item_id: uuid.UUID | None
    detector_run_id: uuid.UUID | None
    author: UserRef
    created_at: datetime


@router.get("/{case_id}/annotations", response_model=list[AnnotationOut])
def list_annotations(case_id: uuid.UUID, p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)):
    cases.get_case(db, p, case_id)
    return (
        db.execute(select(Annotation).where(Annotation.investigation_id == case_id).order_by(Annotation.created_at))
        .scalars()
        .all()
    )


@router.post("/{case_id}/annotations", response_model=AnnotationOut, status_code=201)
def add_annotation(
    case_id: uuid.UUID,
    body: AnnotationIn,
    p: Principal = Depends(require("review.annotate")),
    db: Session = Depends(get_db),
) -> Annotation:
    inv = cases.get_case(db, p, case_id)
    if body.evidence_item_id:
        ev = db.get(EvidenceItem, body.evidence_item_id)
        if ev is None or ev.investigation_id != inv.id:
            raise bad_request("Evidence item is not part of this investigation.")
    a = Annotation(investigation_id=inv.id, author_id=p.user.id, **body.model_dump())
    db.add(a)
    db.flush()
    audit.record(
        db,
        "annotation.added",
        "annotation",
        a.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        details={"kind": a.kind},
    )
    db.commit()
    db.refresh(a)
    return a


# ----------------------------------------------------------------------------- review decisions


ReviewOutcome = Literal[
    "no_reliable_conclusion",
    "inconclusive",
    "some_signals_consistent_with_ai",
    "multiple_compatible_signals_consistent_with_ai",
    "evidence_of_recognized_watermark",
    "provenance_record_verified",
    "provenance_verification_failed",
    "contradictory_evidence",
    "further_analysis_requested",
]


class ReviewIn(BaseModel):
    decision: ReviewOutcome
    rationale: str = Field(min_length=20, max_length=20000)
    agrees_with_automated: bool | None = None
    supersedes_id: uuid.UUID | None = None


class ReviewOut(ORM):
    id: uuid.UUID
    decision: str
    rationale: str
    agrees_with_automated: bool | None
    automated_outcome: str | None
    supersedes_id: uuid.UUID | None
    content_sha256: str
    audit_event_hash: str | None
    reviewer: UserRef
    created_at: datetime


@router.get("/{case_id}/reviews", response_model=list[ReviewOut])
def list_reviews(case_id: uuid.UUID, p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)):
    cases.get_case(db, p, case_id)
    return (
        db.execute(
            select(ReviewDecision).where(ReviewDecision.investigation_id == case_id).order_by(ReviewDecision.created_at)
        )
        .scalars()
        .all()
    )


@router.post("/{case_id}/reviews", response_model=ReviewOut, status_code=201)
def record_review(
    case_id: uuid.UUID, body: ReviewIn, p: Principal = Depends(require("review.decide")), db: Session = Depends(get_db)
) -> ReviewDecision:
    inv = cases.get_case(db, p, case_id, for_update=True)
    if inv.status != "human_review":
        raise conflict("Review decisions can only be recorded while the case is in human review.")
    if inv.created_by_id == p.user.id:
        raise forbidden("Separation of duties: the case creator cannot record the independent review.")
    latest_job = db.execute(
        select(AnalysisJob)
        .where(AnalysisJob.investigation_id == inv.id, AnalysisJob.fusion.is_not(None))
        .order_by(AnalysisJob.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    automated = (latest_job.fusion or {}).get("primary_outcome") if latest_job else None
    content = {
        "investigation_id": str(inv.id),
        "reviewer_id": str(p.user.id),
        "decision": body.decision,
        "rationale": body.rationale,
        "agrees_with_automated": body.agrees_with_automated,
        "automated_outcome": automated,
        "recorded_at": utcnow().isoformat(),
    }
    digest = hashlib.sha256(canonical(content).encode()).hexdigest()
    rd = ReviewDecision(
        investigation_id=inv.id,
        reviewer_id=p.user.id,
        decision=body.decision,
        rationale=body.rationale,
        agrees_with_automated=body.agrees_with_automated,
        automated_outcome=automated,
        supersedes_id=body.supersedes_id,
        content_sha256=digest,
    )
    db.add(rd)
    db.flush()
    ev = audit.record(
        db,
        "review.decision_recorded",
        "review_decision",
        rd.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        details={
            "decision": body.decision,
            "content_sha256": digest,
            "automated_outcome": automated,
            "disagrees_with_automated": body.agrees_with_automated is False,
        },
    )
    rd.audit_event_hash = ev.event_hash
    if body.decision == "further_analysis_requested":
        cases.transition(db, inv, "analysis_queued", actor=p, reason="Reviewer requested further analysis")
    elif body.decision == "inconclusive":
        cases.transition(db, inv, "inconclusive", actor=p, reason="Reviewer recorded an inconclusive assessment")
    inv.disposition = body.decision
    notify(
        db,
        inv.created_by_id,
        p.org_id,
        "review_recorded",
        f"Review recorded: {inv.case_reference}",
        body.decision.replace("_", " "),
        link=f"/cases/{inv.id}",
    )
    db.commit()
    db.refresh(rd)
    return rd


# ----------------------------------------------------------------------------- appeals


class AppealIn(BaseModel):
    grounds: str = Field(min_length=20, max_length=20000)
    report_id: uuid.UUID | None = None
    on_behalf_of: str | None = Field(default=None, max_length=200)


class AppealResolve(BaseModel):
    status: Literal["under_review", "upheld", "corrected", "rejected"]
    resolution: str = Field(min_length=10, max_length=20000)


class AppealOut(ORM):
    id: uuid.UUID
    report_id: uuid.UUID | None
    on_behalf_of: str | None
    grounds: str
    status: str
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


@router.get("/{case_id}/appeals", response_model=list[AppealOut])
def list_appeals(case_id: uuid.UUID, p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)):
    cases.get_case(db, p, case_id)
    return (
        db.execute(select(Appeal).where(Appeal.investigation_id == case_id).order_by(Appeal.created_at)).scalars().all()
    )


@router.post("/{case_id}/appeals", response_model=AppealOut, status_code=201)
def submit_appeal(
    case_id: uuid.UUID, body: AppealIn, p: Principal = Depends(require("appeal.submit")), db: Session = Depends(get_db)
) -> Appeal:
    inv = cases.get_case(db, p, case_id)
    if body.report_id:
        rep = db.get(Report, body.report_id)
        if rep is None or rep.investigation_id != inv.id:
            raise bad_request("Report is not part of this investigation.")
    a = Appeal(investigation_id=inv.id, submitted_by_id=p.user.id, **body.model_dump())
    db.add(a)
    db.flush()
    audit.record(
        db, "appeal.submitted", "appeal", a.id, actor=p.user, organization_id=p.org_id, investigation_id=inv.id, ip=p.ip
    )
    if inv.assigned_reviewer_id:
        notify(
            db,
            inv.assigned_reviewer_id,
            p.org_id,
            "appeal",
            f"Appeal submitted: {inv.case_reference}",
            body.grounds[:140],
            link=f"/cases/{inv.id}",
            severity="warning",
        )
    db.commit()
    db.refresh(a)
    return a


@router.post("/{case_id}/appeals/{appeal_id}/resolve", response_model=AppealOut)
def resolve_appeal(
    case_id: uuid.UUID,
    appeal_id: uuid.UUID,
    body: AppealResolve,
    p: Principal = Depends(require("appeal.resolve")),
    db: Session = Depends(get_db),
) -> Appeal:
    inv = cases.get_case(db, p, case_id)
    a = db.get(Appeal, appeal_id)
    if a is None or a.investigation_id != inv.id:
        raise not_found("appeal")
    if a.status in ("upheld", "corrected", "rejected"):
        raise conflict("Appeal already resolved.")
    if a.submitted_by_id == p.user.id:
        raise forbidden("An appeal cannot be resolved by the person who submitted it.")
    a.status, a.resolution = body.status, body.resolution
    if body.status != "under_review":
        a.resolved_by_id, a.resolved_at = p.user.id, utcnow()
    audit.record(
        db,
        "appeal.updated",
        "appeal",
        a.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        ip=p.ip,
        details={"status": body.status},
    )
    db.commit()
    db.refresh(a)
    return a


# ----------------------------------------------------------------------------- deletion workflow


class DeletionIn(BaseModel):
    reason: str = Field(min_length=10, max_length=4000)


@router.post("/{case_id}/deletion-requests", status_code=201)
def request_deletion(
    case_id: uuid.UUID,
    body: DeletionIn,
    p: Principal = Depends(require("retention.request_deletion")),
    db: Session = Depends(get_db),
) -> dict:
    inv = cases.get_case(db, p, case_id)
    status = "blocked" if inv.legal_hold else "pending"
    dr = DeletionRequest(investigation_id=inv.id, requested_by_id=p.user.id, reason=body.reason, status=status)
    db.add(dr)
    db.flush()
    audit.record(
        db,
        "retention.deletion_requested",
        "deletion_request",
        dr.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        reason=body.reason,
        ip=p.ip,
        details={"blocked_by_legal_hold": inv.legal_hold},
    )
    db.commit()
    return {
        "id": str(dr.id),
        "status": dr.status,
        "note": "Blocked: the investigation is under legal hold."
        if inv.legal_hold
        else "Awaiting approval by a second authorised person.",
    }


class DeletionDecision(BaseModel):
    approve: bool
    reason: str = Field(min_length=5, max_length=4000)


@router.post("/{case_id}/deletion-requests/{request_id}/decide")
def decide_deletion(
    case_id: uuid.UUID,
    request_id: uuid.UUID,
    body: DeletionDecision,
    p: Principal = Depends(require("retention.approve_deletion")),
    db: Session = Depends(get_db),
) -> dict:
    from app.services.evidence import purge_binaries

    inv = cases.get_case(db, p, case_id, for_update=True)
    dr = db.get(DeletionRequest, request_id)
    if dr is None or dr.investigation_id != inv.id:
        raise not_found("deletion request")
    if dr.status != "pending":
        raise conflict(f"Request is {dr.status}.")
    if dr.requested_by_id == p.user.id:
        raise forbidden("Two-person rule: the requester cannot approve their own deletion request.")
    if inv.legal_hold:
        dr.status = "blocked"
        db.commit()
        raise conflict("Investigation is under legal hold; deletion is blocked.")
    dr.decided_by_id, dr.decided_at = p.user.id, utcnow()
    purged = 0
    if body.approve:
        for item in db.execute(select(EvidenceItem).where(EvidenceItem.investigation_id == inv.id)).scalars():
            purged += purge_binaries(db, item, p.user, body.reason)
        dr.status, dr.executed_at = "executed", utcnow()
    else:
        dr.status = "rejected"
    audit.record(
        db,
        "retention.deletion_decided",
        "deletion_request",
        dr.id,
        actor=p.user,
        organization_id=p.org_id,
        investigation_id=inv.id,
        reason=body.reason,
        ip=p.ip,
        details={"approved": body.approve, "versions_purged": purged},
    )
    db.commit()
    return {
        "id": str(dr.id),
        "status": dr.status,
        "versions_purged": purged,
        "note": "Stored bytes were removed; hash records, audit events and tombstones are retained.",
    }


@router.get("/{case_id}/deletion-requests")
def list_deletion_requests(
    case_id: uuid.UUID, p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)
) -> list[dict]:
    cases.get_case(db, p, case_id)
    rows = db.execute(select(DeletionRequest).where(DeletionRequest.investigation_id == case_id)).scalars()
    return [
        {
            "id": str(r.id),
            "status": r.status,
            "reason": r.reason,
            "created_at": r.created_at,
            "decided_at": r.decided_at,
            "executed_at": r.executed_at,
        }
        for r in rows
    ]


# ----------------------------------------------------------------------------- history


@router.get("/{case_id}/history")
def case_history(
    case_id: uuid.UUID,
    p: Principal = Depends(require("case.read")),
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=1000),
) -> list[dict]:
    cases.get_case(db, p, case_id)
    rows = db.execute(
        select(AuditEvent).where(AuditEvent.investigation_id == case_id).order_by(AuditEvent.seq.desc()).limit(limit)
    ).scalars()
    return [
        {
            "seq": e.seq,
            "id": str(e.id),
            "occurred_at": e.occurred_at,
            "actor": e.actor_label,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "reason": e.reason,
            "details": e.details,
            "event_hash": e.event_hash,
        }
        for e in rows
    ]


@router.get("/{case_id}/reviewers")
def eligible_reviewers(
    case_id: uuid.UUID, p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)
) -> list[dict]:
    inv = cases.get_case(db, p, case_id)
    rows = db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == p.org_id, User.is_active.is_(True))
    ).all()
    return [
        {"id": str(u.id), "display_name": u.display_name, "email": u.email, "role": m.role_id}
        for u, m in rows
        if "review.decide" in role_permissions(m.role_id) and u.id != inv.created_by_id
    ]
