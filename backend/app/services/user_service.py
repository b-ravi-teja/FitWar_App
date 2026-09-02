"""Profile read/update use cases behind `GET/PATCH /me`."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.users import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)

    async def update_profile(
        self,
        user: User,
        *,
        display_name: str | None,
        notification_preferences: dict[str, Any] | None,
    ) -> User:
        await self._users.update_profile(
            user, display_name=display_name, notification_preferences=notification_preferences
        )
        return user
