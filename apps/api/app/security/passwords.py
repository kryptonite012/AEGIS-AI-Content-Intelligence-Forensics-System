from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_ph = PasswordHasher()  # Argon2id with library defaults (RFC 9106 low-memory profile)
MIN_PASSWORD_LENGTH = 12
_DUMMY = _ph.hash("timing-equalisation-dummy-password")


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, hashed: str | None) -> bool:
    try:
        return _ph.verify(hashed or _DUMMY, password) and hashed is not None
    except (VerificationError, InvalidHashError):
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.lower() == password or password.upper() == password:
        problems.append("must mix upper- and lower-case letters")
    if not any(c.isdigit() for c in password):
        problems.append("must contain a digit")
    return problems
