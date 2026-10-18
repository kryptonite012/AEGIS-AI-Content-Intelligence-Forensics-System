"""Overview, search, notifications, audit, health, detectors, model registry and administration."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.config import get_settings
from app.core.errors import bad_request, conflict, forbidden, not_found
from app.db import get_db, utcnow
from app.models import (
    AnalysisJob,
    AuditEvent,
    BenchmarkRun,
    CalibrationProfile,
    DetectorRun,
    DetectorVersion,
    EvidenceItem,
    EvidenceVersion,
    Investigation,
    Membership,
    Notification,
    Organization,
    ProvenanceRecord,
    RetentionPolicy,
    SystemSetting,
    User,
    UserSession,
)
from app.security.deps import Principal, get_principal, require, require_system_admin
from app.security.passwords import hash_password, password_problems
from app.security.permissions import PERMISSIONS, ROLES
from app.services import health as health_svc
from app.services import investigations as cases
from app.services.analysis import recover_stale_jobs, registry

router = APIRouter(tags=["platform"])


# ----------------------------------------------------------------------------- overview


@router.get("/overview")
def overview(p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)) -> dict:
    """Dashboard figures. Every number is a live database count for the caller's organisation."""
    visible = cases.visible_cases(p).subquery()
    ids = select(visible.c.id)
    status_counts = dict(db.execute(select(visible.c.status, func.count()).group_by(visible.c.status)).all())
    total = sum(status_counts.values())
    demo = db.execute(select(func.count()).select_from(visible).where(visible.c.is_demo_fixture.is_(True))).scalar_one()
    evidence = db.execute(
        select(func.count()).select_from(EvidenceItem).where(EvidenceItem.investigation_id.in_(ids))
    ).scalar_one()
    jobs = dict(
        db.execute(
            select(AnalysisJob.status, func.count())
            .where(AnalysisJob.investigation_id.in_(ids))
            .group_by(AnalysisJob.status)
        ).all()
    )
    outcomes: dict[str, int] = {}
    for f in db.execute(
        select(AnalysisJob.fusion).where(AnalysisJob.investigation_id.in_(ids), AnalysisJob.fusion.is_not(None))
    ).scalars():
        key = (f or {}).get("primary_outcome", "unknown")
        outcomes[key] = outcomes.get(key, 0) + 1
    runs = dict(
        db.execute(
            select(DetectorRun.status, func.count())
            .join(AnalysisJob)
            .where(AnalysisJob.investigation_id.in_(ids))
            .group_by(DetectorRun.status)
        ).all()
    )
    recent = db.execute(cases.visible_cases(p).order_by(Investigation.updated_at.desc()).limit(8)).scalars().all()
    events = (
        db.execute(
            select(AuditEvent).where(AuditEvent.organization_id == p.org_id).order_by(AuditEvent.seq.desc()).limit(10)
        )
        .scalars()
        .all()
        if p.can("audit.read")
        else []
    )
    since = utcnow() - timedelta(days=30)
    daily = (
        db.execute(
            select(func.date_trunc("day", AnalysisJob.created_at).label("d"), func.count())
            .where(AnalysisJob.investigation_id.in_(ids), AnalysisJob.created_at >= since)
            .group_by("d")
            .order_by("d")
        ).all()
        if db.get_bind().dialect.name == "postgresql"
        else []
    )
    latest_bench = db.execute(
        select(BenchmarkRun)
        .where(BenchmarkRun.status == "completed")
        .order_by(BenchmarkRun.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return {
        "source": "live database counts",
        "investigations": {
            "total": total,
            "by_status": status_counts,
            "demo_fixtures": demo,
            "awaiting_review": status_counts.get("human_review", 0),
            "inconclusive": status_counts.get("inconclusive", 0),
        },
        "evidence_items": evidence,
        "jobs": {
            "by_status": jobs,
            "completed": jobs.get("completed", 0) + jobs.get("completed_with_failures", 0),
            "active": jobs.get("queued", 0) + jobs.get("running", 0),
        },
        "detector_runs": runs,
        "automated_outcomes": outcomes,
        "jobs_per_day": [{"day": d.date().isoformat(), "count": n} for d, n in daily],
        "recent_cases": [
            {
                "id": str(i.id),
                "case_reference": i.case_reference,
                "title": i.title,
                "status": i.status,
                "priority": i.priority,
                "updated_at": i.updated_at,
                "is_demo_fixture": i.is_demo_fixture,
            }
            for i in recent
        ],
        "recent_audit_events": [
            {
                "seq": e.seq,
                "action": e.action,
                "actor": e.actor_label,
                "occurred_at": e.occurred_at,
                "entity_type": e.entity_type,
            }
            for e in events
        ],
        "latest_benchmark": None
        if latest_bench is None
        else {
            "id": str(latest_bench.id),
            "method_id": latest_bench.method_id,
            "result_kind": latest_bench.result_kind,
            "auroc": ((latest_bench.metrics or {}).get("overall") or {}).get("auroc"),
            "n": ((latest_bench.metrics or {}).get("overall") or {}).get("n"),
            "finished_at": latest_bench.finished_at,
        },
    }


@router.get("/search")
def search(
    q: str = Query(min_length=2, max_length=200),
    p: Principal = Depends(require("case.read")),
    db: Session = Depends(get_db),
) -> dict:
    like = f"%{q}%"
    inv = db.execute(
        cases.visible_cases(p)
        .where(or_(Investigation.title.ilike(like), Investigation.case_reference.ilike(like)))
        .limit(10)
    ).scalars()
    ids = cases.visible_cases(p).with_only_columns(Investigation.id)
    ev = (
        db.execute(
            select(EvidenceItem)
            .where(
                EvidenceItem.investigation_id.in_(ids),
                or_(
                    EvidenceItem.display_name.ilike(like),
                    EvidenceItem.id.in_(
                        select(EvidenceVersion.evidence_item_id).where(EvidenceVersion.sha256.startswith(q.lower()))
                    ),
                ),
            )
            .limit(10)
        ).scalars()
        if p.can("evidence.read")
        else []
    )
    return {
        "investigations": [
            {"id": str(i.id), "case_reference": i.case_reference, "title": i.title, "status": i.status} for i in inv
        ],
        "evidence": [
            {
                "id": str(e.id),
                "investigation_id": str(e.investigation_id),
                "display_name": e.display_name,
                "modality": e.modality,
            }
            for e in ev
        ],
    }


@router.get("/notifications")
def notifications(
    p: Principal = Depends(get_principal), db: Session = Depends(get_db), unread_only: bool = False
) -> dict:
    q = select(Notification).where(Notification.user_id == p.user.id)
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    rows = db.execute(q.order_by(Notification.created_at.desc()).limit(50)).scalars().all()
    unread = db.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == p.user.id, Notification.read_at.is_(None))
    ).scalar_one()
    return {
        "unread": unread,
        "items": [
            {
                "id": str(n.id),
                "kind": n.kind,
                "severity": n.severity,
                "title": n.title,
                "body": n.body,
                "link": n.link,
                "created_at": n.created_at,
                "read_at": n.read_at,
            }
            for n in rows
        ],
    }


@router.post("/notifications/read", status_code=204, response_model=None)
def mark_read(ids: list[uuid.UUID] | None = None, p: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    q = select(Notification).where(Notification.user_id == p.user.id, Notification.read_at.is_(None))
    if ids:
        q = q.where(Notification.id.in_(ids))
    for n in db.execute(q).scalars():
        n.read_at = utcnow()
    db.commit()


# ----------------------------------------------------------------------------- audit


@router.get("/audit/events")
def audit_events(
    p: Principal = Depends(require("audit.read")),
    db: Session = Depends(get_db),
    action: str | None = None,
    investigation_id: uuid.UUID | None = None,
    before_seq: int | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[dict]:
    q = select(AuditEvent).where(
        or_(
            AuditEvent.organization_id == p.org_id,
            AuditEvent.organization_id.is_(None) & (AuditEvent.actor_user_id == p.user.id),
        )
    )
    if action:
        q = q.where(AuditEvent.action.startswith(action))
    if investigation_id:
        q = q.where(AuditEvent.investigation_id == investigation_id)
    if before_seq:
        q = q.where(AuditEvent.seq < before_seq)
    rows = db.execute(q.order_by(AuditEvent.seq.desc()).limit(limit)).scalars()
    return [
        {
            "seq": e.seq,
            "id": str(e.id),
            "occurred_at": e.occurred_at,
            "actor": e.actor_label,
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "investigation_id": str(e.investigation_id) if e.investigation_id else None,
            "reason": e.reason,
            "details": e.details,
            "correlation_id": e.correlation_id,
            "prev_hash": e.prev_hash,
            "event_hash": e.event_hash,
        }
        for e in rows
    ]


@router.post("/audit/verify")
def verify_audit(p: Principal = Depends(require("audit.read")), db: Session = Depends(get_db)) -> dict:
    result = audit.verify_chain(db)
    audit.record(
        db,
        "audit.chain_verified",
        "audit",
        None,
        actor=p.user,
        organization_id=p.org_id,
        ip=p.ip,
        details={"valid": result["valid"], "checked": result["checked"]},
    )
    db.commit()
    return {
        **result,
        "limitation": "Detects edits to or removal of individual events. A privileged actor able to "
        "rewrite the whole table could recompute the chain; anchor the head externally.",
    }


@router.get("/audit/head")
def audit_head(p: Principal = Depends(require("audit.read")), db: Session = Depends(get_db)) -> dict:
    e = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
    return {
        "seq": e.seq if e else 0,
        "event_hash": e.event_hash if e else audit.GENESIS,
        "occurred_at": e.occurred_at if e else None,
        "purpose": "Record this value in a separately controlled system to anchor the chain.",
    }


# ----------------------------------------------------------------------------- health


@router.get("/health/live", tags=["health"])
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/ready", tags=["health"])
def ready(db: Session = Depends(get_db)) -> dict:
    comps = health_svc.components(db)
    core = {c["id"]: c["status"] for c in comps if c["id"] in ("database", "storage")}
    return {"status": "ready" if all(v == "operational" for v in core.values()) else "degraded", "core": core}


@router.get("/health/components", tags=["health"])
def components(p: Principal = Depends(require("system.health")), db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    return {
        "mode": str(s.mode),
        "environment": s.environment,
        "components": health_svc.components(db),
        "methods": health_svc.methods(),
        "jobs": health_svc.queue_stats(db),
        "external_processing_enabled": s.allow_external_processing,
    }


@router.get("/detectors", tags=["detectors"])
def detectors(p: Principal = Depends(require("analysis.read")), db: Session = Depends(get_db)) -> list[dict]:
    regs = {d.method_id: d for d in db.execute(select(DetectorVersion)).scalars()}
    out = []
    for m in health_svc.methods():
        r = regs.get(m["id"])
        out.append(
            {
                **m,
                "registry": None
                if r is None
                else {
                    "id": str(r.id),
                    "validation_status": r.validation_status,
                    "enabled": r.enabled,
                    "operating_threshold": r.operating_threshold,
                    "languages_evaluated": r.languages_evaluated,
                    "license": r.license,
                    "validation_benchmark_run_id": str(r.validation_benchmark_run_id)
                    if r.validation_benchmark_run_id
                    else None,
                },
            }
        )
    return out


@router.get("/provenance/records", tags=["provenance"])
def provenance_records(p: Principal = Depends(require("analysis.read")), db: Session = Depends(get_db)) -> list[dict]:
    ids = cases.visible_cases(p).with_only_columns(Investigation.id)
    rows = db.execute(
        select(ProvenanceRecord, EvidenceItem)
        .join(EvidenceItem)
        .where(EvidenceItem.investigation_id.in_(ids))
        .order_by(ProvenanceRecord.verified_at.desc())
        .limit(200)
    ).all()
    return [
        {
            "id": str(pr.id),
            "evidence_id": str(e.id),
            "investigation_id": str(e.investigation_id),
            "evidence_name": e.display_name,
            "state": pr.state,
            "standard": pr.standard,
            "trust_anchor": pr.trust_anchor,
            "verified_at": pr.verified_at,
            "signer": (pr.summary or {}).get("signature"),
            "claim_generator": (pr.summary or {}).get("claim_generator"),
            "declared_ai_source": (pr.summary or {}).get("declared_ai_source"),
            "failure_codes": (pr.summary or {}).get("failure_codes"),
        }
        for pr, e in rows
    ]


@router.get("/watermarks/verifiers", tags=["provenance"])
def watermark_verifiers(p: Principal = Depends(require("analysis.read"))) -> list[dict]:
    return [
        m for m in health_svc.methods() if m["evidence_class"] in ("verified_watermark", "cryptographic_provenance")
    ]


# ----------------------------------------------------------------------------- users & organisations


@router.get("/reviewers", tags=["investigations"])
def reviewer_candidates(p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)) -> list[dict]:
    """Active organisation members who hold the review permission (excluding the caller)."""
    from app.security.permissions import role_permissions

    rows = db.execute(
        select(User, Membership)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.organization_id == p.org_id, User.is_active.is_(True))
    ).all()
    return [
        {"id": str(u.id), "display_name": u.display_name, "role": m.role_id}
        for u, m in rows
        if "review.decide" in role_permissions(m.role_id) and u.id != p.user.id
    ]


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=2, max_length=200)
    password: str = Field(max_length=256)
    role: Literal["org_admin", "investigator", "forensic_analyst", "independent_reviewer", "auditor", "researcher"]


@router.get("/users", tags=["admin"])
def list_users(p: Principal = Depends(require("admin.users")), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(User, Membership)
        .join(Membership)
        .where(Membership.organization_id == p.org_id)
        .order_by(User.display_name)
    ).all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name,
            "role": m.role_id,
            "role_name": ROLES[m.role_id][0],
            "is_active": u.is_active,
            "mfa_enabled": u.mfa_enabled,
            "last_login_at": u.last_login_at,
            "is_demo_account": u.is_demo_account,
        }
        for u, m in rows
    ]


@router.post("/users", status_code=201, tags=["admin"])
def create_user(
    body: UserCreate, p: Principal = Depends(require("admin.users")), db: Session = Depends(get_db)
) -> dict:
    if problems := password_problems(body.password):
        raise bad_request("Password " + "; ".join(problems) + ".", "weak_password")
    email = body.email.lower()
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(email=email, display_name=body.display_name, password_hash=hash_password(body.password))
        db.add(user)
        db.flush()
    elif db.execute(
        select(Membership).where(Membership.user_id == user.id, Membership.organization_id == p.org_id)
    ).first():
        raise conflict("User is already a member of this organisation.")
    db.add(Membership(user_id=user.id, organization_id=p.org_id, role_id=body.role))
    audit.record(
        db,
        "admin.user_added",
        "user",
        user.id,
        actor=p.user,
        organization_id=p.org_id,
        ip=p.ip,
        details={"email": email, "role": body.role},
    )
    db.commit()
    return {"id": str(user.id), "email": email, "role": body.role}


class MemberPatch(BaseModel):
    role: (
        Literal["org_admin", "investigator", "forensic_analyst", "independent_reviewer", "auditor", "researcher"] | None
    ) = None
    is_active: bool | None = None


@router.patch("/users/{user_id}", tags=["admin"])
def update_member(
    user_id: uuid.UUID, body: MemberPatch, p: Principal = Depends(require("admin.users")), db: Session = Depends(get_db)
) -> dict:
    m = db.execute(
        select(Membership).where(Membership.user_id == user_id, Membership.organization_id == p.org_id)
    ).scalar_one_or_none()
    if m is None:
        raise not_found("user")
    if user_id == p.user.id:
        raise forbidden("Administrators cannot change their own role or status.")
    user = db.get(User, user_id)
    assert user
    changes: dict[str, Any] = {}
    if body.role:
        changes["role"] = [m.role_id, body.role]
        m.role_id = body.role
    if body.is_active is not None:
        if not p.user.is_system_admin and len(user.memberships) > 1:
            raise forbidden("Users with several memberships can only be deactivated by a system administrator.")
        changes["is_active"] = [user.is_active, body.is_active]
        user.is_active = body.is_active
        if not body.is_active:
            for s in db.execute(
                select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
            ).scalars():
                s.revoked_at = utcnow()
    audit.record(
        db, "admin.user_updated", "user", user_id, actor=p.user, organization_id=p.org_id, ip=p.ip, details=changes
    )
    db.commit()
    return {"id": str(user_id), "role": m.role_id, "is_active": user.is_active}


@router.post("/users/{user_id}/revoke-sessions", status_code=204, tags=["admin"], response_model=None)
def revoke_sessions(user_id: uuid.UUID, p: Principal = Depends(require("admin.users")), db: Session = Depends(get_db)):
    if not db.execute(
        select(Membership).where(Membership.user_id == user_id, Membership.organization_id == p.org_id)
    ).first():
        raise not_found("user")
    n = 0
    for s in db.execute(
        select(UserSession).where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
    ).scalars():
        s.revoked_at = utcnow()
        n += 1
    audit.record(
        db,
        "admin.sessions_revoked",
        "user",
        user_id,
        actor=p.user,
        organization_id=p.org_id,
        ip=p.ip,
        details={"sessions": n},
    )
    db.commit()


@router.get("/roles", tags=["admin"])
def roles(p: Principal = Depends(get_principal)) -> dict:
    return {
        "roles": [
            {"id": rid, "name": name, "description": desc, "permissions": sorted(perms)}
            for rid, (name, desc, perms) in ROLES.items()
        ],
        "permissions": PERMISSIONS,
    }


class OrgIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")


@router.get("/organizations", tags=["admin"])
def organizations(p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> list[dict]:
    q = (
        select(Organization)
        if p.user.is_system_admin
        else select(Organization).join(Membership).where(Membership.user_id == p.user.id)
    )
    return [
        {"id": str(o.id), "name": o.name, "slug": o.slug, "allow_external_processing": o.allow_external_processing}
        for o in db.execute(q).scalars()
    ]


@router.post("/organizations", status_code=201, tags=["admin"])
def create_org(body: OrgIn, p: Principal = Depends(require_system_admin), db: Session = Depends(get_db)) -> dict:
    if db.execute(select(Organization).where(Organization.slug == body.slug)).first():
        raise conflict("Slug already in use.")
    o = Organization(name=body.name, slug=body.slug)
    db.add(o)
    db.flush()
    db.add(Membership(user_id=p.user.id, organization_id=o.id, role_id="system_admin"))
    for cls, days in (("standard", 365), ("extended", 365 * 7), ("legal_minimum", 90), ("research", 365 * 3)):
        db.add(RetentionPolicy(organization_id=o.id, classification=cls, retain_days=days))
    audit.record(db, "admin.organization_created", "organization", o.id, actor=p.user, organization_id=o.id, ip=p.ip)
    db.commit()
    return {"id": str(o.id), "name": o.name, "slug": o.slug}


class OrgSettings(BaseModel):
    allow_external_processing: bool
    reason: str = Field(min_length=10, max_length=2000)


@router.put("/organizations/current/settings", tags=["admin"])
def org_settings(body: OrgSettings, p: Principal = Depends(require("admin.settings")), db: Session = Depends(get_db)):
    org = db.get(Organization, p.org_id)
    assert org
    before = org.allow_external_processing
    org.allow_external_processing = body.allow_external_processing
    audit.record(
        db,
        "admin.org_settings_changed",
        "organization",
        org.id,
        actor=p.user,
        organization_id=org.id,
        reason=body.reason,
        ip=p.ip,
        details={"allow_external_processing": [before, body.allow_external_processing]},
    )
    db.commit()
    return {
        "allow_external_processing": org.allow_external_processing,
        "deployment_kill_switch": get_settings().allow_external_processing,
        "note": "External providers run only when the deployment, the organisation AND the case all permit it.",
    }


# ----------------------------------------------------------------------------- model registry


class RegistryPatch(BaseModel):
    enabled: bool | None = None
    license: str | None = Field(default=None, max_length=200)
    model_identifier: str | None = Field(default=None, max_length=300)
    languages_evaluated: list[str] | None = None
    validation_status: Literal["unvalidated", "validated", "deprecated"] | None = None
    validation_benchmark_run_id: uuid.UUID | None = None
    calibration_profile_id: uuid.UUID | None = None
    operating_threshold: float | None = None
    validation_note: str | None = Field(default=None, max_length=4000)
    reason: str = Field(min_length=10, max_length=4000)


def _reg_dict(r: DetectorVersion) -> dict:
    return {c.name: getattr(r, c.name) for c in DetectorVersion.__table__.columns}


@router.get("/models", tags=["models"])
def models(p: Principal = Depends(require("analysis.read")), db: Session = Depends(get_db)) -> list[dict]:
    last = {}
    for run in db.execute(
        select(BenchmarkRun).where(BenchmarkRun.status == "completed").order_by(BenchmarkRun.finished_at)
    ).scalars():
        last[run.method_id] = {
            "id": str(run.id),
            "result_kind": run.result_kind,
            "finished_at": run.finished_at,
            "auroc": ((run.metrics or {}).get("overall") or {}).get("auroc"),
        }
    avail = {m["id"]: m for m in health_svc.methods()}
    return [
        {
            **_reg_dict(r),
            "last_benchmark": last.get(r.method_id),
            "operational": avail.get(r.method_id, {}).get("available", False),
            "availability_reason": avail.get(r.method_id, {}).get("availability_reason"),
        }
        for r in db.execute(select(DetectorVersion).order_by(DetectorVersion.method_id)).scalars()
    ]


@router.patch("/models/{registry_id}", tags=["models"])
def update_model(
    registry_id: uuid.UUID,
    body: RegistryPatch,
    p: Principal = Depends(require("admin.models")),
    db: Session = Depends(get_db),
) -> dict:
    r = db.get(DetectorVersion, registry_id)
    if r is None:
        raise not_found("model")
    changes = body.model_dump(exclude_unset=True, exclude={"reason"})
    target_status = changes.get("validation_status", r.validation_status)
    if target_status == "validated":
        run_id = changes.get("validation_benchmark_run_id", r.validation_benchmark_run_id)
        run = db.get(BenchmarkRun, run_id) if run_id else None
        if run is None or run.status != "completed" or run.method_id != r.method_id:
            raise bad_request("Marking a detector validated requires a completed benchmark run of this method.")
        if run.result_kind != "locally_measured":
            raise bad_request(
                "Validation requires locally measured results on registered real data, not "
                f"'{run.result_kind}' results."
            )
        prof_id = changes.get("calibration_profile_id", r.calibration_profile_id)
        if prof_id is not None:
            prof = db.get(CalibrationProfile, prof_id)
            if prof is None or not prof.validated or prof.method_id != r.method_id:
                raise bad_request("Calibration profile must be validated and belong to this method.")
    before = {k: getattr(r, k) for k in changes}
    for k, v in changes.items():
        setattr(r, k, v)
    audit.record(
        db,
        "admin.model_registry_changed",
        "detector_version",
        r.id,
        actor=p.user,
        organization_id=p.org_id,
        reason=body.reason,
        ip=p.ip,
        details={"method_id": r.method_id, "before": before, "after": changes},
    )
    db.commit()
    return _reg_dict(r)


# ----------------------------------------------------------------------------- settings, retention, queues


SETTING_KEYS = {"feature.research_bench": bool, "feature.chunked_uploads": bool, "ui.banner": str}


class SettingIn(BaseModel):
    value: Any
    reason: str = Field(min_length=5, max_length=2000)


@router.get("/admin/settings", tags=["admin"])
def get_settings_view(p: Principal = Depends(require("admin.settings")), db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    stored = {x.key: x.value for x in db.execute(select(SystemSetting)).scalars()}
    return {
        "runtime": {
            "mode": str(s.mode),
            "environment": s.environment,
            "task_mode": s.task_mode,
            "storage_backend": s.storage_backend,
            "max_upload_mb": s.max_upload_mb,
            "max_text_upload_mb": s.max_text_upload_mb,
            "require_malware_scan": s.require_malware_scan,
            "allow_external_processing": s.allow_external_processing,
            "login_rate_limit_per_minute": s.login_rate_limit_per_minute,
            "upload_rate_limit_per_hour": s.upload_rate_limit_per_hour,
            "api_rate_limit_per_minute": s.api_rate_limit_per_minute,
            "access_token_minutes": s.access_token_minutes,
        },
        "feature_flags": {k: stored.get(k) for k in SETTING_KEYS},
        "note": "Runtime values come from environment variables and require a restart to change.",
    }


@router.put("/admin/settings/{key}", tags=["admin"])
def put_setting(key: str, body: SettingIn, p: Principal = Depends(require_system_admin), db: Session = Depends(get_db)):
    if key not in SETTING_KEYS or not isinstance(body.value, SETTING_KEYS[key]):
        raise bad_request(f"Unknown setting or wrong type; allowed: {sorted(SETTING_KEYS)}")
    row = db.get(SystemSetting, key) or SystemSetting(key=key)
    before = row.value
    row.value, row.updated_by_id = body.value, p.user.id
    db.add(row)
    audit.record(
        db,
        "admin.setting_changed",
        "system_setting",
        key,
        actor=p.user,
        reason=body.reason,
        ip=p.ip,
        details={"before": before, "after": body.value},
    )
    db.commit()
    return {"key": key, "value": body.value}


class RetentionIn(BaseModel):
    retain_days: int = Field(ge=1, le=365 * 100)
    description: str = Field(default="", max_length=2000)
    reason: str = Field(min_length=5, max_length=2000)


@router.get("/admin/retention", tags=["admin"])
def retention(p: Principal = Depends(require("case.read")), db: Session = Depends(get_db)) -> dict:
    pols = db.execute(select(RetentionPolicy).where(RetentionPolicy.organization_id == p.org_id)).scalars().all()
    due = []
    for pol in pols:
        cutoff = utcnow() - timedelta(days=pol.retain_days)
        for inv in db.execute(
            cases.visible_cases(p).where(
                Investigation.retention_class == pol.classification, Investigation.created_at < cutoff
            )
        ).scalars():
            due.append(
                {
                    "id": str(inv.id),
                    "case_reference": inv.case_reference,
                    "legal_hold": inv.legal_hold,
                    "classification": pol.classification,
                }
            )
    return {
        "policies": [
            {"classification": x.classification, "retain_days": x.retain_days, "description": x.description}
            for x in pols
        ],
        "due_for_review": due,
        "note": "Retention review lists cases past their period. Deletion always needs a request and a second "
        "person's approval, and is blocked under legal hold.",
    }


@router.put("/admin/retention/{classification}", tags=["admin"])
def put_retention(
    classification: str,
    body: RetentionIn,
    p: Principal = Depends(require("admin.settings")),
    db: Session = Depends(get_db),
) -> dict:
    pol = db.execute(
        select(RetentionPolicy).where(
            RetentionPolicy.organization_id == p.org_id, RetentionPolicy.classification == classification
        )
    ).scalar_one_or_none()
    if pol is None:
        raise not_found("retention policy")
    before = pol.retain_days
    pol.retain_days, pol.description = body.retain_days, body.description
    audit.record(
        db,
        "admin.retention_changed",
        "retention_policy",
        pol.id,
        actor=p.user,
        organization_id=p.org_id,
        reason=body.reason,
        ip=p.ip,
        details={"classification": classification, "retain_days": [before, body.retain_days]},
    )
    db.commit()
    return {"classification": classification, "retain_days": pol.retain_days}


@router.post("/admin/jobs/recover", tags=["admin"])
def recover(p: Principal = Depends(require_system_admin), db: Session = Depends(get_db)) -> dict:
    n = recover_stale_jobs(db)
    audit.record(db, "admin.jobs_recovered", "analysis_job", None, actor=p.user, ip=p.ip, details={"jobs": n})
    db.commit()
    return {"requeued_or_failed": n}


@router.get("/governance/compliance", tags=["governance"])
def compliance(p: Principal = Depends(get_principal)) -> dict:
    path = Path(__file__).resolve().parents[5] / "docs" / "governance" / "compliance-mapping.json"
    if not path.is_file():
        raise not_found("compliance mapping")
    return json.loads(path.read_text())


@router.get("/governance/registry-summary", tags=["governance"])
def registry_summary(p: Principal = Depends(get_principal)) -> dict:
    reg = registry()
    by: dict[str, int] = {}
    for m in reg.values():
        by[str(m.info.implementation)] = by.get(str(m.info.implementation), 0) + 1
    return {"methods": len(reg), "by_implementation_status": by}
