from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Notification


def notify(
    db: Session,
    user_id: uuid.UUID,
    org_id: uuid.UUID | None,
    kind: str,
    title: str,
    body: str = "",
    link: str | None = None,
    severity: str = "info",
) -> Notification:
    n = Notification(
        user_id=user_id, organization_id=org_id, kind=kind, title=title[:200], body=body, link=link, severity=severity
    )
    db.add(n)
    return n
