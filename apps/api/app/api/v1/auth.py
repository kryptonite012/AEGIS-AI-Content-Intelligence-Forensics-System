from __future__ import annotations

import uuid
from datetime import timedelta

import pyotp
from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import service as audit
from app.core.config import get_settings
from app.core.errors import AppError, bad_request, not_found
from app.core.ratelimit import check as rate_check
from app.db import get_db, utcnow
from app.models import Membership, User, UserSession
from app.security.deps import Principal, client_ip, get_principal
from app.security.passwords import hash_password, password_problems, verify_password
from app.security.permissions import ROLES, role_permissions
from app.security.tokens import (
    create_access_token,
    decrypt_field,
    encrypt_field,
    hash_refresh_token,
    new_refresh_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE = "aegis_refresh"
LOCK_AFTER = 10


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)
    totp: str | None = Field(default=None, max_length=10)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


def _set_refresh_cookie(resp: Response, raw: str) -> None:
    s = get_settings()
    resp.set_cookie(
        REFRESH_COOKIE,
        raw,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        max_age=s.refresh_token_days * 86400,
        path="/api/v1/auth",
    )


def _require_csrf_header(x_requested_with: str | None) -> None:
    # Cookie-authenticated endpoints require a custom header that cross-site forms cannot set.
    if x_requested_with != "aegis-web":
        raise AppError(403, "csrf", "Missing X-Requested-With: aegis-web header.")


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> TokenOut:
    s = get_settings()
    ip = client_ip(request) or "unknown"
    email = body.email.lower()
    rate_check("login", f"{ip}:{email}", s.login_rate_limit_per_minute, 60)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = utcnow()
    if user and user.locked_until and user.locked_until > now:
        raise AppError(423, "account_locked", "Account temporarily locked after repeated failures.")
    ok = verify_password(body.password, user.password_hash if user else None)
    if ok and user and user.mfa_enabled:
        if not body.totp:
            raise AppError(401, "mfa_required", "A one-time code is required.")
        ok = pyotp.TOTP(decrypt_field(user.mfa_secret_encrypted or "")).verify(body.totp, valid_window=1)
    if not ok or user is None or not user.is_active:
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= LOCK_AFTER:
                user.locked_until, user.failed_login_count = now + timedelta(minutes=15), 0
            audit.record(db, "auth.login_failed", "user", user.id, actor_label=email, ip=ip)
            db.commit()
        raise AppError(401, "invalid_credentials", "Invalid email, password or code.")
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
    raw, digest = new_refresh_token()
    sess = UserSession(
        user_id=user.id,
        refresh_token_hash=digest,
        expires_at=now + timedelta(days=s.refresh_token_days),
        user_agent=(request.headers.get("user-agent") or "")[:300],
        ip_address=ip,
    )
    db.add(sess)
    db.flush()
    audit.record(db, "auth.login", "user", user.id, actor=user, ip=ip, details={"session_id": str(sess.id)})
    db.commit()
    token, exp = create_access_token(user.id, sess.id)
    _set_refresh_cookie(response, raw)
    return TokenOut(access_token=token, expires_in=exp)


@router.post("/refresh", response_model=TokenOut)
def refresh(
    response: Response,
    db: Session = Depends(get_db),
    aegis_refresh: str | None = Cookie(default=None),
    x_requested_with: str | None = Header(default=None),
) -> TokenOut:
    _require_csrf_header(x_requested_with)
    if not aegis_refresh:
        raise AppError(401, "unauthenticated", "No refresh token.")
    sess = db.execute(
        select(UserSession).where(UserSession.refresh_token_hash == hash_refresh_token(aegis_refresh))
    ).scalar_one_or_none()
    if sess is None or sess.revoked_at or sess.expires_at < utcnow():
        raise AppError(401, "unauthenticated", "Session expired or revoked.")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise AppError(401, "unauthenticated", "Account is not active.")
    raw, digest = new_refresh_token()  # rotate on every use
    sess.refresh_token_hash = digest
    db.commit()
    token, exp = create_access_token(user.id, sess.id)
    _set_refresh_cookie(response, raw)
    return TokenOut(access_token=token, expires_in=exp)


@router.post("/logout", status_code=204, response_model=None)
def logout(response: Response, p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> Response:
    sess = db.get(UserSession, p.session_id)
    if sess:
        sess.revoked_at = utcnow()
    audit.record(db, "auth.logout", "user", p.user.id, actor=p.user, ip=p.ip)
    db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/v1/auth")
    response.status_code = 204
    return response


@router.get("/me")
def me(p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    memberships = db.execute(select(Membership).where(Membership.user_id == p.user.id)).scalars().all()
    s = get_settings()
    return {
        "id": str(p.user.id),
        "email": p.user.email,
        "display_name": p.user.display_name,
        "is_system_admin": p.user.is_system_admin,
        "mfa_enabled": p.user.mfa_enabled,
        "is_demo_account": p.user.is_demo_account,
        "organization": {
            "id": str(p.org_id),
            "name": p.organization.name,
            "slug": p.organization.slug,
            "allow_external_processing": p.organization.allow_external_processing,
        },
        "role": p.role,
        "role_name": ROLES[p.role][0],
        "permissions": sorted(p.permissions),
        "memberships": [
            {
                "organization_id": str(m.organization_id),
                "organization_name": m.organization.name,
                "role": m.role_id,
                "role_name": ROLES[m.role_id][0],
            }
            for m in memberships
        ],
        "environment": {
            "mode": str(s.mode),
            "environment": s.environment,
            "task_mode": s.task_mode,
            "external_processing_enabled": s.allow_external_processing,
        },
    }


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(max_length=256)


@router.post("/change-password", status_code=204, response_model=None)
def change_password(body: PasswordChange, p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> None:
    if not verify_password(body.current_password, p.user.password_hash):
        raise AppError(401, "invalid_credentials", "Current password is incorrect.")
    if problems := password_problems(body.new_password):
        raise bad_request("Password " + "; ".join(problems) + ".", "weak_password")
    p.user.password_hash = hash_password(body.new_password)
    for s in db.execute(
        select(UserSession).where(
            UserSession.user_id == p.user.id, UserSession.id != p.session_id, UserSession.revoked_at.is_(None)
        )
    ).scalars():
        s.revoked_at = utcnow()
    audit.record(db, "auth.password_changed", "user", p.user.id, actor=p.user, ip=p.ip)
    db.commit()


@router.post("/mfa/setup")
def mfa_setup(p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    secret = pyotp.random_base32()
    p.user.mfa_secret_encrypted = encrypt_field(secret)
    p.user.mfa_enabled = False
    db.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=p.user.email, issuer_name="AEGIS")
    return {"secret": secret, "otpauth_uri": uri, "note": "Confirm with /auth/mfa/enable using a current code."}


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=10)


@router.post("/mfa/enable", status_code=204, response_model=None)
def mfa_enable(body: CodeIn, p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> None:
    if not p.user.mfa_secret_encrypted or not pyotp.TOTP(decrypt_field(p.user.mfa_secret_encrypted)).verify(
        body.code, valid_window=1
    ):
        raise bad_request("Invalid one-time code.", "invalid_code")
    p.user.mfa_enabled = True
    audit.record(db, "auth.mfa_enabled", "user", p.user.id, actor=p.user, ip=p.ip)
    db.commit()


@router.get("/sessions")
def sessions(p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(UserSession).where(UserSession.user_id == p.user.id).order_by(UserSession.created_at.desc()).limit(50)
    ).scalars()
    return [
        {
            "id": str(s.id),
            "created_at": s.created_at,
            "expires_at": s.expires_at,
            "revoked_at": s.revoked_at,
            "user_agent": s.user_agent,
            "ip_address": s.ip_address,
            "current": s.id == p.session_id,
        }
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204, response_model=None)
def revoke_session(session_id: uuid.UUID, p: Principal = Depends(get_principal), db: Session = Depends(get_db)) -> None:
    s = db.get(UserSession, session_id)
    if s is None or s.user_id != p.user.id:
        raise not_found("session")
    s.revoked_at = utcnow()
    audit.record(db, "auth.session_revoked", "user_session", s.id, actor=p.user, ip=p.ip)
    db.commit()


def permissions_for(role: str) -> list[str]:
    return sorted(role_permissions(role))
