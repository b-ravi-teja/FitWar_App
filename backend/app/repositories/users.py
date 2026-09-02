import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.user import User, UserProfile, UserStatus


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        # Eager-loads `profile` — every authenticated request resolves a User via
        # this method (core/deps.py's current_user), and most callers that need a
        # User at all end up wanting profile fields too (display_name, xp_total).
        # Async ORM lazy-loading a relationship outside an awaited context raises
        # MissingGreenlet, so this is eager by default rather than a per-caller trap.
        result = await self._session.execute(
            select(User).where(User.id == user_id).options(selectinload(User.profile))
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create(self, *, email: str, password_hash: str, display_name: str) -> User:
        user = User(email=email, password_hash=password_hash)
        user.profile = UserProfile(display_name=display_name)
        self._session.add(user)
        await self._session.flush()
        return user

    async def soft_delete(self, user: User) -> None:
        user.status = UserStatus.DELETED
        user.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def update_password_hash(self, user: User, *, password_hash: str) -> None:
        user.password_hash = password_hash
        await self._session.flush()

    async def update_profile(
        self,
        user: User,
        *,
        display_name: str | None = None,
        notification_preferences: dict[str, Any] | None = None,
    ) -> None:
        if display_name is not None:
            user.profile.display_name = display_name
        if notification_preferences is not None:
            user.profile.notification_preferences = notification_preferences
        await self._session.flush()
