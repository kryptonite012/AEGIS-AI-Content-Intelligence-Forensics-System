"""Investigation access control and workflow state machine.

draft -> evidence_acquired -> analysis_queued -> analysis_complete -> human_review
      -> report_finalized -> archived
human_review -> inconclusive -> report_finalized
human_review / analysis_complete -> analysis_queued   (further analysis requested)
report_finalized / inconclusive / archived -> human_review   (controlled reopening; reason required)
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.errors import AppError, conflict, forbidden, not_found
from app.models import Investigation
from app.security.deps import Principal

STATES = (
    "draft",
    "evidence_acquired",
    "analysis_queued",
    "analysis_complete",
    "human_review",
    "inconclusive",
    "report_finalized",
    "archived",
)

TRANSITIONS: dict[str, set[str]] = {
    "draft": {"evidence_acquired"},
    "evidence_acquired": {"analysis_queued"},
    "analysis_queued": {"analysis_complete"},
    "analysis_complete": {"human_review", "analysis_queued"},
    "human_review": {"inconclusive", "report_finalized", "analysis_queued"},
    "inconclusive": {"report_finalized", "human_review"},
    "report_finalized": {"archived", "human_review"},
    "archived": {"human_review"},
}
REOPEN_FROM = {"report_finalized", "inconclusive", "archived"}
EVIDENCE_MUTABLE_STATES = {"draft", "evidence_acquired", "analysis_queued", "analysis_complete", "human_review"}
LOCKED_STATES = {"report_finalized", "archived"}


def visible_cases(p: Principal) -> Select:
    q = select(Investigation).where(Investigation.organization_id == p.org_id)
    if not p.can("case.read_restricted"):
        q = q.where(
            or_(
                Investigation.access_classification != "restricted",
                Investigation.created_by_id == p.user.id,
                Investigation.assigned_reviewer_id == p.user.id,
            )
        )
    return q


def get_case(db: Session, p: Principal, case_id: uuid.UUID, *, for_update: bool = False) -> Investigation:
    if not p.can("case.read"):
        raise forbidden()
    q = visible_cases(p).where(Investigation.id == case_id)
    if for_update and db.get_bind().dialect.name == "postgresql":
        q = q.with_for_update()
    inv = db.execute(q).scalar_one_or_none()
    if inv is None:
        raise not_found("investigation")
    return inv


def ensure_unlocked(inv: Investigation) -> None:
    if inv.status in LOCKED_STATES:
        raise conflict(f"Investigation is {inv.status}; reopen it with a recorded reason before making changes.")


def transition(
    db: Session,
    inv: Investigation,
    target: str,
    *,
    actor: Principal | None,
    reason: str | None = None,
    automatic: bool = False,
) -> None:
    if target == inv.status:
        return
    if target not in TRANSITIONS.get(inv.status, set()):
        raise AppError(
            409,
            "invalid_transition",
            f"Cannot move from {inv.status} to {target}.",
            {"allowed": sorted(TRANSITIONS.get(inv.status, set()))},
        )
    if inv.status in REOPEN_FROM and target == "human_review":
        if actor is None or not actor.can("case.reopen"):
            raise forbidden("Reopening requires the case.reopen permission.")
        if not reason or len(reason.strip()) < 10:
            raise AppError(422, "reason_required", "Reopening requires a reason of at least 10 characters.")
    previous = inv.status
    inv.status = target
    if target == "archived":
        from app.db import utcnow

        inv.archived_at = utcnow()
    audit.record(
        db,
        "investigation.status_changed",
        "investigation",
        inv.id,
        actor=actor.user if actor else None,
        actor_label=None if actor else "system:workflow",
        organization_id=inv.organization_id,
        investigation_id=inv.id,
        reason=reason,
        details={"from": previous, "to": target, "automatic": automatic},
        ip=actor.ip if actor else None,
    )


def advance_if(db: Session, inv: Investigation, from_states: set[str], target: str) -> None:
    """Automatic workflow progression (e.g. first evidence upload)."""
    if inv.status in from_states:
        transition(db, inv, target, actor=None, automatic=True)
