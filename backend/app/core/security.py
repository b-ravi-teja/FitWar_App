"""Password hashing (Argon2id) and JWT access-token encode/decode.

Pure crypto/encoding utilities — no DB access, no FastAPI imports. `domain/` and
`services/` call these directly; they are not request-scoped dependencies.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return str(_pwd_context.hash(plain_password))


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bool(_pwd_context.verify(plain_password, password_hash))


def create_access_token(*, subject: str) -> str:
    settings = get_settings().auth
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
        "type": "access",
    }
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


class InvalidTokenError(Exception):
    """Raised when an access token is malformed, expired, or has the wrong type."""


def decode_access_token(token: str) -> str:
    """Returns the subject (user id) from a valid access token, or raises InvalidTokenError."""
    settings = get_settings().auth
    try:
        payload = jwt.decode(
            token, settings.jwt_secret.get_secret_value(), algorithms=[settings.jwt_algorithm]
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("type") != "access":
        raise InvalidTokenError("Not an access token")

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise InvalidTokenError("Missing subject claim")

    return subject


def generate_refresh_token() -> str:
    """A random opaque token — never a JWT. The raw value is only ever seen once, by the client."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    """Refresh tokens are stored server-side as a hash, never the raw value (Architecture §6).

    Deliberately SHA-256, not Argon2: Argon2's per-hash random salt makes it
    impossible to look a token up by hash equality, which token rotation needs on
    every `/auth/refresh` call. That's the right tradeoff *because* the input here
    is a 48-byte cryptographically random token, not a human password — there's no
    dictionary/brute-force risk a slow, salted hash would defend against, so a fast
    deterministic digest is both correct and necessary for an indexed lookup.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
