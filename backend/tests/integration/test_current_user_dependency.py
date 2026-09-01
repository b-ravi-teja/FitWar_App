"""Direct tests of the `current_user` auth dependency against a real DB session.

There is no `/me` endpoint in Phase 1 to exercise this through HTTP (Architecture
§17's Foundation phase scopes in the token infrastructure and the dependency itself,
not a profile endpoint) — so it's tested directly, the same way a unit test would
exercise any other dependency function.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt as pyjwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.deps import current_user
from app.core.security import create_access_token
from app.domain.auth.exceptions import UnauthenticatedError
from app.repositories.users import UserRepository


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_current_user_valid_token(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).create(
        email="ravi@example.com", password_hash="x", display_name="Ravi"
    )
    token = create_access_token(subject=str(user.id))
    request = SimpleNamespace(state=SimpleNamespace())

    resolved = await current_user(request, _bearer(token), db_session)  # type: ignore[arg-type]
    assert resolved.id == user.id
    assert request.state.user_id == str(user.id)


async def test_current_user_missing_token(db_session: AsyncSession) -> None:
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(UnauthenticatedError):
        await current_user(request, None, db_session)  # type: ignore[arg-type]


async def test_current_user_invalid_token(db_session: AsyncSession) -> None:
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(UnauthenticatedError):
        await current_user(request, _bearer("garbage.not.a.jwt"), db_session)  # type: ignore[arg-type]


async def test_current_user_expired_token(db_session: AsyncSession) -> None:
    user = await UserRepository(db_session).create(
        email="ravi2@example.com", password_hash="x", display_name="Ravi"
    )
    settings = get_settings().auth
    now = datetime.now(UTC)
    expired_token = pyjwt.encode(
        {
            "sub": str(user.id),
            "type": "access",
            "iat": now - timedelta(hours=1),
            "exp": now - timedelta(minutes=1),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(UnauthenticatedError):
        await current_user(request, _bearer(expired_token), db_session)  # type: ignore[arg-type]


async def test_current_user_deleted_user(db_session: AsyncSession) -> None:
    users = UserRepository(db_session)
    user = await users.create(email="gone@example.com", password_hash="x", display_name="Gone")
    token = create_access_token(subject=str(user.id))
    await users.soft_delete(user)

    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(UnauthenticatedError):
        await current_user(request, _bearer(token), db_session)  # type: ignore[arg-type]
