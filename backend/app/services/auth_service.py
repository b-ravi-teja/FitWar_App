"""Auth use cases: register, login, refresh, logout.

Orchestrates domain rules + repositories + `core/security` crypto helpers. Never
touches SQLAlchemy directly (that's the repositories' job) and never constructs an
HTTP response (that's the API layer's job) — only raises typed domain exceptions.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.domain.auth.exceptions import (
    AccountDeletedError,
    EmailAlreadyTakenError,
    InvalidCredentialsError,
    RefreshTokenInvalidError,
    RefreshTokenReuseDetectedError,
)
from app.models.auth import RefreshToken
from app.models.user import User, UserStatus
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int  # access token TTL, in seconds


class UserRepositoryProtocol(Protocol):
    """What AuthService needs from a user repository — structural, not the concrete
    SQLAlchemy-backed class, so fakes in unit tests are legitimately type-compatible."""

    async def get_by_email(self, email: str) -> User | None: ...
    async def create(self, *, email: str, password_hash: str, display_name: str) -> User: ...
    async def soft_delete(self, user: User) -> None: ...


class RefreshTokenRepositoryProtocol(Protocol):
    async def create(
        self, *, user_id: uuid.UUID, token_hash: str, family_id: uuid.UUID, expires_at: datetime
    ) -> RefreshToken: ...
    async def get_by_hash(self, token_hash: str) -> RefreshToken | None: ...
    async def revoke(self, token: RefreshToken) -> None: ...
    async def revoke_family(self, family_id: uuid.UUID) -> None: ...


class AuthService:
    _users: UserRepositoryProtocol
    _refresh_tokens: RefreshTokenRepositoryProtocol

    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def register(
        self, *, email: str, password: str, display_name: str
    ) -> tuple[User, TokenPair]:
        if await self._users.get_by_email(email) is not None:
            raise EmailAlreadyTakenError(f"An account with email {email} already exists.")

        user = await self._users.create(
            email=email, password_hash=hash_password(password), display_name=display_name
        )
        tokens = await self._issue_tokens(user.id, family_id=uuid.uuid4())
        return user, tokens

    async def login(self, *, email: str, password: str) -> tuple[User, TokenPair]:
        user = await self._users.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError("Incorrect email or password.")
        if user.status != UserStatus.ACTIVE:
            raise AccountDeletedError("This account has been deleted.")

        tokens = await self._issue_tokens(user.id, family_id=uuid.uuid4())
        return user, tokens

    async def refresh(self, *, raw_refresh_token: str) -> TokenPair:
        stored = await self._refresh_tokens.get_by_hash(hash_refresh_token(raw_refresh_token))
        if stored is None:
            raise RefreshTokenInvalidError("Refresh token not recognized.")

        if stored.revoked_at is not None:
            # A revoked token was presented again — treat as possible theft and
            # revoke the whole family, not just this token (Architecture §6).
            await self._refresh_tokens.revoke_family(stored.family_id)
            raise RefreshTokenReuseDetectedError("Refresh token has already been used.")

        if stored.expires_at < datetime.now(UTC):
            raise RefreshTokenInvalidError("Refresh token has expired.")

        await self._refresh_tokens.revoke(stored)
        return await self._issue_tokens(stored.user_id, family_id=stored.family_id)

    async def logout(self, *, raw_refresh_token: str) -> None:
        stored = await self._refresh_tokens.get_by_hash(hash_refresh_token(raw_refresh_token))
        if stored is not None and stored.revoked_at is None:
            await self._refresh_tokens.revoke(stored)

    async def _issue_tokens(self, user_id: uuid.UUID, *, family_id: uuid.UUID) -> TokenPair:
        settings = get_settings().auth
        raw_refresh = generate_refresh_token()
        await self._refresh_tokens.create(
            user_id=user_id,
            token_hash=hash_refresh_token(raw_refresh),
            family_id=family_id,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days),
        )
        return TokenPair(
            access_token=create_access_token(subject=str(user_id)),
            refresh_token=raw_refresh,
            expires_in=settings.access_token_expire_minutes * 60,
        )
