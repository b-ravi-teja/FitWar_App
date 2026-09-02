"""Health connection use cases (connect / list / revoke).

A connection records that a user intends this app to read a health source. It is not
proof of an OS-level permission grant: HealthKit gives no API to read back read-scope
authorization (Apple hides refusals so apps can't detect them), so the honest signals
are the user's own action and `last_synced_at`, which the server sets only when
evidence actually arrives.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.verification.exceptions import HealthConnectionNotFoundError
from app.models.verification import HealthConnection, HealthProvider
from app.repositories.verification import HealthConnectionRepository


class HealthConnectionService:
    def __init__(self, session: AsyncSession) -> None:
        self._connections = HealthConnectionRepository(session)

    async def list_for_user(self, user_id: uuid.UUID) -> list[HealthConnection]:
        return await self._connections.list_for_user(user_id)

    async def connect(
        self, *, user_id: uuid.UUID, provider: HealthProvider
    ) -> HealthConnection:
        return await self._connections.connect(user_id, provider)

    async def revoke(self, *, user_id: uuid.UUID, connection_id: uuid.UUID) -> None:
        """Revoking is scoped to the caller — another account's id simply doesn't exist
        here, which is also why this can't be used to probe for valid connection ids."""
        connection = await self._connections.get_by_id(user_id, connection_id)
        if connection is None:
            raise HealthConnectionNotFoundError("No such health connection.")
        await self._connections.revoke(connection)
