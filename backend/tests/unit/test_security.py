import time

import jwt
import pytest

from app.core.security import (
    InvalidTokenError,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)


def test_password_hash_rejects_wrong_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_password_hash_is_argon2() -> None:
    assert hash_password("anything").startswith("$argon2")


def test_access_token_roundtrip() -> None:
    token = create_access_token(subject="user-123")
    assert decode_access_token(token) == "user-123"


def test_access_token_rejects_tampered_signature() -> None:
    token = create_access_token(subject="user-123")
    with pytest.raises(InvalidTokenError):
        decode_access_token(token + "tampered")


def test_access_token_rejects_wrong_type() -> None:
    from app.core.config import get_settings

    settings = get_settings().auth
    refresh_shaped = jwt.encode(
        {"sub": "user-123", "type": "refresh"},
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(InvalidTokenError):
        decode_access_token(refresh_shaped)


def test_refresh_token_hash_is_deterministic() -> None:
    """Unlike password hashing, refresh-token hashing must be deterministic — the
    repository looks tokens up by exact hash equality on every /auth/refresh call."""
    raw = generate_refresh_token()
    assert hash_refresh_token(raw) == hash_refresh_token(raw)


def test_refresh_tokens_are_unique() -> None:
    assert generate_refresh_token() != generate_refresh_token()


def test_access_tokens_change_second_to_second() -> None:
    """Sanity check that `iat` is actually being set (not a frozen/stale value)."""
    token_a = create_access_token(subject="user-123")
    time.sleep(1.1)
    token_b = create_access_token(subject="user-123")
    assert token_a != token_b
