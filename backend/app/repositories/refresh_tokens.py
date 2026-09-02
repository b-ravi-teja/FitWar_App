import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, user_id: uuid.UUID, token_hash: str, family_id: uuid.UUID, expires_at: datetime
    ) -> RefreshToken:
        token = RefreshToken(
            user_id=user_id, token_hash=token_hash, family_id=family_id, expires_at=expires_at
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def revoke(self, token: RefreshToken) -> None:
        token.revoked_at = datetime.now(UTC)
        await self._session.flush()

    async def revoke_family(self, family_id: uuid.UUID) -> None:
        """Reuse-detection response: revoke every token in the family (Architecture §6)."""
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        """Password reset is a full re-authentication event (ADR 0007) — every
        outstanding refresh token for the user is revoked, not just one family."""
        await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
