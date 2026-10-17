"""Authentication and authorisation dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError, forbidden
from app.core.ratelimit import check as rate_check
from app.db import get_db, utcnow
from app.models import Membership, Organization, User, UserSession
from app.security.permissions import role_permissions
from app.security.tokens import decode_access_token


@dataclass
class Principal:
    user: User
    session_id: uuid.UUID
    organization: Organization
    role: str
    permissions: set[str]
    ip: str | None

    def can(self, perm: str) -> bool:
        return perm in self.permissions

    @property
    def org_id(self) -> uuid.UUID:
        return self.organization.id


def _unauth(msg: str = "Authentication required.") -> AppError:
    return AppError(401, "unauthenticated", msg)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_principal(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_aegis_organization: str | None = Header(default=None),
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise _unauth()
    try:
        claims = decode_access_token(authorization.split(" ", 1)[1])
    except jwt.ExpiredSignatureError as exc:
        raise _unauth("Access token expired.") from exc
    except jwt.PyJWTError as exc:
        raise _unauth("Invalid access token.") from exc
    session = db.get(UserSession, uuid.UUID(claims["sid"]))
    if session is None or session.revoked_at is not None or session.expires_at < utcnow():
        raise _unauth("Session has been revoked or has expired.")
    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active or session.user_id != user.id:
        raise _unauth("Account is not active.")
    memberships = db.execute(select(Membership).where(Membership.user_id == user.id)).scalars().all()
    if not memberships:
        raise forbidden("Account has no organisation membership.")
    chosen = memberships[0]
    if x_aegis_organization:
        match = [m for m in memberships if str(m.organization_id) == x_aegis_organization]
        if not match:
            raise forbidden("You are not a member of the requested organisation.")
        chosen = match[0]
    perms = role_permissions(chosen.role_id)
    s = get_settings()
    rate_check("api", str(user.id), s.api_rate_limit_per_minute, 60)
    request.state.user_id = str(user.id)
    return Principal(user, session.id, chosen.organization, chosen.role_id, perms, client_ip(request))


def require(*perms: str):
    def dep(p: Principal = Depends(get_principal)) -> Principal:
        missing = [x for x in perms if not p.can(x)]
        if missing:
            raise forbidden(f"Missing permission: {', '.join(missing)}")
        return p

    return dep


def require_system_admin(p: Principal = Depends(get_principal)) -> Principal:
    if not p.user.is_system_admin:
        raise forbidden("System administrator privileges required.")
    return p
