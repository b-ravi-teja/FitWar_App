import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserProfile, UserStatus


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

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
