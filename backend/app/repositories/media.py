"""Persistence for media assets."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import MediaAsset, MediaContextType, MediaStatus


class MediaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        owner_id: uuid.UUID,
        storage_key: str,
        content_type: str,
        context_type: MediaContextType,
        expires_at: datetime,
    ) -> MediaAsset:
        asset = MediaAsset(
            owner_id=owner_id,
            storage_key=storage_key,
            content_type=content_type,
            context_type=context_type,
            status=MediaStatus.PENDING,
            expires_at=expires_at,
        )
        self._session.add(asset)
        await self._session.flush()
        return asset

    async def get(self, media_id: uuid.UUID) -> MediaAsset | None:
        result = await self._session.execute(
            select(MediaAsset).where(MediaAsset.id == media_id)
        )
        return result.scalar_one_or_none()

    async def get_owned(self, media_id: uuid.UUID, owner_id: uuid.UUID) -> MediaAsset | None:
        """Owner-scoped: another user's media id simply does not resolve."""
        result = await self._session.execute(
            select(MediaAsset).where(
                MediaAsset.id == media_id, MediaAsset.owner_id == owner_id
            )
        )
        return result.scalar_one_or_none()

    async def due_for_deletion(self, now: datetime, *, limit: int) -> list[MediaAsset]:
        """Objects past their retention deadline that still exist.

        A NULL `expires_at` is excluded by the comparison itself — which is exactly how
        a pending-review proof is protected from cleanup.
        """
        result = await self._session.execute(
            select(MediaAsset)
            .where(
                MediaAsset.expires_at.is_not(None),
                MediaAsset.expires_at <= now,
                MediaAsset.object_deleted_at.is_(None),
                MediaAsset.status != MediaStatus.EXPIRED,
            )
            .order_by(MediaAsset.expires_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())
