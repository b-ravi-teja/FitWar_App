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

    async def revoke(self, token: RefreshToken) -> bool:
        """Revoke one token. Returns whether *this* call is the one that revoked it.

        A conditional UPDATE rather than an attribute assignment, so rotation is atomic:
        two requests presenting the same token race on `revoked_at IS NULL` and exactly
        one wins. The loser learns it lost from the row count and is treated as reuse —
        without this, both could read `revoked_at is None`, both pass the check, and
        both mint a token from one presentation, which is precisely the property
        rotation exists to prevent.
        """
        result = await self._session.execute(
            update(RefreshToken)
            .where(RefreshToken.id == token.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
            .returning(RefreshToken.id)
        )
        await self._session.flush()
        return result.scalar_one_or_none() is not None

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
