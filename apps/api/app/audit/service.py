"""Append-only, hash-chained audit trail.

event_hash = SHA-256(prev_hash || canonical_json(event fields)). The chain makes silent edits or
deletions of individual events detectable by :func:`verify_chain`. Limitation: a privileged
database administrator could rewrite the entire chain consistently; detecting that requires
anchoring the chain head to a separately controlled system (see /api/v1/audit/head and
docs/security/audit-chain.md).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.logging import correlation_id_var
from app.db import utcnow
from app.models import AuditEvent, User

GENESIS = "0" * 64
_LOCK_KEY = 0x4AE615  # advisory lock id serialising chain appends on PostgreSQL


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def _hash_fields(ev: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(ev.id),
        "occurred_at": ev.occurred_at.isoformat() if isinstance(ev.occurred_at, datetime) else str(ev.occurred_at),
        "organization_id": str(ev.organization_id) if ev.organization_id else None,
        "actor_user_id": str(ev.actor_user_id) if ev.actor_user_id else None,
        "actor_label": ev.actor_label,
        "action": ev.action,
        "entity_type": ev.entity_type,
        "entity_id": ev.entity_id,
        "investigation_id": str(ev.investigation_id) if ev.investigation_id else None,
        "reason": ev.reason,
        "details": ev.details,
    }


def compute_hash(prev_hash: str, ev: AuditEvent) -> str:
    return hashlib.sha256((prev_hash + canonical(_hash_fields(ev))).encode()).hexdigest()


def record(
    db: Session,
    action: str,
    entity_type: str,
    entity_id: Any = None,
    *,
    actor: User | None = None,
    actor_label: str | None = None,
    organization_id: uuid.UUID | None = None,
    investigation_id: uuid.UUID | None = None,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEvent:
    """Append an event in the caller's transaction (it commits or rolls back with the operation)."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    last = db.execute(select(AuditEvent.event_hash).order_by(AuditEvent.seq.desc()).limit(1)).scalar()
    prev = last or GENESIS
    ev = AuditEvent(
        id=uuid.uuid4(),
        occurred_at=utcnow(),
        organization_id=organization_id,
        actor_user_id=actor.id if actor else None,
        actor_label=actor_label or (actor.email if actor else "system"),
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        investigation_id=investigation_id,
        reason=reason,
        details=json.loads(canonical(details or {})),
        correlation_id=correlation_id_var.get(),
        ip_address=ip,
        prev_hash=prev,
    )
    ev.event_hash = compute_hash(prev, ev)
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session, limit: int | None = None) -> dict[str, Any]:
    prev = GENESIS
    checked = 0
    q = select(AuditEvent).order_by(AuditEvent.seq)
    for ev in db.execute(q.execution_options(yield_per=500)).scalars():
        if ev.prev_hash != prev:
            return {"valid": False, "checked": checked, "broken_at_seq": ev.seq, "reason": "prev_hash mismatch"}
        if compute_hash(prev, ev) != ev.event_hash:
            return {"valid": False, "checked": checked, "broken_at_seq": ev.seq, "reason": "event content altered"}
        prev = ev.event_hash
        checked += 1
        if limit and checked >= limit:
            break
    return {"valid": True, "checked": checked, "head": prev}
