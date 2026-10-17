"""Short-lived JWT access tokens bound to revocable server-side sessions; opaque refresh tokens."""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

ALGORITHM = "HS256"
ISSUER = "aegis"


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID) -> tuple[str, int]:
    s = get_settings()
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=s.access_token_minutes)
    token = jwt.encode(
        {
            "sub": str(user_id),
            "sid": str(session_id),
            "iat": now,
            "exp": exp,
            "iss": ISSUER,
            "typ": "access",
            "jti": secrets.token_hex(8),
        },
        s.secret_key,
        algorithm=ALGORITHM,
    )
    return token, s.access_token_minutes * 60


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        get_settings().secret_key,
        algorithms=[ALGORITHM],
        issuer=ISSUER,
        options={"require": ["exp", "sub", "sid", "iss"]},
    )


def new_refresh_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _fernet() -> Fernet:
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"aegis-field-encryption", info=b"mfa-secrets").derive(
        get_settings().secret_key.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_field(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_field(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
