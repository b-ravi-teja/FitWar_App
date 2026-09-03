"""Media upload lifecycle and retention (Architecture §9, §33).

Postgres holds metadata; the bytes live in object storage and are deleted aggressively.
The security properties this file is responsible for:

- The storage key is **server-generated** and namespaced by owner, so a client can
  neither choose a key nor write over someone else's object.
- The presigned grant is short-lived and pins content type and maximum size, so limits
  are enforced by storage rather than merely promised by the client.
- The client never receives bucket credentials — only a single-object, expiring grant.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.media.exceptions import (
    MediaNotFoundError,
    MediaNotReadyError,
    MediaTypeNotAllowedError,
    MediaUploadNotFoundInStorageError,
)
from app.integrations.storage.base import PresignedUpload
from app.integrations.storage.s3 import get_object_storage
from app.models.media import (
    MediaAsset,
    MediaContextType,
    MediaStatus,
)
from app.repositories.media import MediaRepository

logger = get_logger(__name__)


class MediaService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = MediaRepository(session)
        self._storage = get_object_storage()
        self._settings = get_settings().media

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def prepare_upload(
        self,
        *,
        owner_id: uuid.UUID,
        content_type: str,
        context_type: MediaContextType,
        now: datetime | None = None,
    ) -> tuple[MediaAsset, PresignedUpload]:
        """Create a PENDING asset and return a short-lived grant to fill it.

        The asset expires quickly from the moment it is created: an upload that never
        becomes a submitted proof is abandoned, and nothing should be paying to store it
        (§33). Submitting a proof clears that deadline.
        """
        now = now or datetime.now(UTC)
        normalized = content_type.strip().lower()
        if normalized not in self._settings.allowed_video_types:
            raise MediaTypeNotAllowedError(
                f"'{content_type}' isn't an accepted proof format."
            )

        # Owner-namespaced and random. The owner prefix makes cross-user overwrite
        # impossible even if a key were somehow guessed; the uuid makes it unguessable.
        extension = "mov" if normalized == "video/quicktime" else "mp4"
        key = f"{context_type.value}/{owner_id}/{uuid.uuid4()}.{extension}"

        asset = await self._repo.create(
            owner_id=owner_id,
            storage_key=key,
            content_type=normalized,
            context_type=context_type,
            expires_at=now + timedelta(hours=self._settings.abandoned_upload_ttl_hours),
        )
        grant = self._storage.presigned_upload(
            key=key,
            content_type=normalized,
            max_bytes=self._settings.max_proof_bytes,
            expires_in=self._settings.upload_url_ttl_seconds,
        )
        return asset, grant

    async def complete_upload(
        self, *, owner_id: uuid.UUID, media_id: uuid.UUID
    ) -> MediaAsset:
        """Confirm the object landed. Idempotent — re-confirming returns the same asset.

        The server checks storage itself rather than trusting the client's word: size and
        content type are read back from the object that actually exists.
        """
        asset = await self._repo.get_owned(media_id, owner_id)
        if asset is None:
            raise MediaNotFoundError("No such media.")
        if asset.status is MediaStatus.PROCESSED:
            return asset
        if asset.status is MediaStatus.EXPIRED:
            raise MediaNotReadyError("That upload expired. Start a new one.")

        head = self._storage.head(key=asset.storage_key)
        if head is None:
            asset.status = MediaStatus.FAILED
            await self._session.flush()
            raise MediaUploadNotFoundInStorageError("No uploaded file found for that media.")

        size, actual_type = head
        # Trust the object, not the request: the declared type at prepare time is only a
        # promise until there is a real object to inspect.
        asset.size_bytes = size
        if actual_type:
            asset.content_type = actual_type.lower()
        asset.status = MediaStatus.PROCESSED
        await self._session.flush()
        return asset

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    async def playback_url(self, asset: MediaAsset) -> str | None:
        """A short-lived signed GET, or None once the object is gone.

        Returning None rather than a dead URL is what lets the UI say "no longer
        available" instead of showing a player that will never load (§27).
        """
        if asset.status is not MediaStatus.PROCESSED or asset.object_deleted_at is not None:
            return None
        return self._storage.presigned_download(
            key=asset.storage_key, expires_in=self._settings.download_url_ttl_seconds
        )

    async def get_owned(self, media_id: uuid.UUID, owner_id: uuid.UUID) -> MediaAsset:
        asset = await self._repo.get_owned(media_id, owner_id)
        if asset is None:
            # Same 404 a nonexistent id produces — holding an id is not authorization,
            # and a distinct error would confirm the object exists.
            raise MediaNotFoundError("No such media.")
        return asset

    async def require_processed(self, media_id: uuid.UUID, owner_id: uuid.UUID) -> MediaAsset:
        asset = await self.get_owned(media_id, owner_id)
        if asset.status is not MediaStatus.PROCESSED:
            raise MediaNotReadyError("That upload hasn't finished.")
        return asset

    # ------------------------------------------------------------------
    # Retention
    # ------------------------------------------------------------------

    async def protect_from_cleanup(self, asset: MediaAsset) -> None:
        """Clear the expiry deadline while a proof awaits review.

        The mandatory rule (§6): a pending-review video is never deleted, because the
        reviewer still has to watch it.
        """
        asset.expires_at = None
        await self._session.flush()

    async def schedule_deletion(
        self, asset: MediaAsset, *, resolved_at: datetime
    ) -> None:
        """Start the retention clock once a proof is approved or rejected."""
        asset.expires_at = resolved_at + timedelta(
            hours=self._settings.resolved_retention_hours
        )
        await self._session.flush()

    async def run_cleanup(self, *, now: datetime | None = None, limit: int = 500) -> int:
        """Delete objects whose retention has elapsed. Returns how many were removed.

        Idempotent and crash-safe by construction:
        - Only rows with a non-null `expires_at` in the past are considered, so a
          pending-review proof (NULL deadline) is structurally excluded.
        - Storage delete is a no-op for an already-absent object.
        - The row is marked EXPIRED with `object_deleted_at` **only when storage actually
          confirmed the delete**. A failed delete leaves the row untouched so the next
          pass retries it; recording it as gone would orphan the bytes forever behind
          metadata claiming they were removed.
        - One object's failure does not abort the sweep — the rest of the batch still runs.
        - The metadata row is kept: decision, reviewer, timestamps and competitive
          outcome all survive the video (§6).
        """
        now = now or datetime.now(UTC)
        due = await self._repo.due_for_deletion(now, limit=limit)
        deleted = 0
        failed = 0
        for asset in due:
            if not self._storage.delete(key=asset.storage_key):
                failed += 1
                continue
            asset.status = MediaStatus.EXPIRED
            asset.object_deleted_at = now
            deleted += 1
            logger.info("media_object_deleted", media_id=str(asset.id))
        if deleted:
            await self._session.flush()
        if failed:
            # Surfaced rather than swallowed: a persistent non-zero count here means
            # storage is rejecting deletes and retention has silently stopped working.
            logger.warning("media_cleanup_deletes_failed", failed=failed, attempted=len(due))
        return deleted
