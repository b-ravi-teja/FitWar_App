"""Media assets and group chat (Architecture §9, §10 ERD).

Postgres holds metadata only — never bytes. The object itself lives in S3-compatible
storage under a server-generated key, and is deleted aggressively (§33: storage cost is
a product constraint) while this row survives as the durable record.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin


class MediaStatus(enum.StrEnum):
    """Upload lifecycle. `EXPIRED` is Phase 6's addition to the frozen
    pending|processed|failed set: it marks a row whose object has been deleted by
    retention, so the app can say "no longer available" instead of showing a broken
    player against a key that no longer resolves."""

    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    EXPIRED = "expired"


class MediaVisibility(enum.StrEnum):
    PRIVATE = "private"
    GROUP_SHARED = "group_shared"


class MediaContextType(enum.StrEnum):
    VERIFICATION_PROOF = "verification_proof"
    CHAT = "chat"
    AVATAR = "avatar"
    GROUP_COVER = "group_cover"


class MediaAsset(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "media_asset"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_media_asset_storage_key"),
        Index("ix_media_asset_owner", "owner_id"),
        # Drives the cleanup sweep: find everything due for deletion cheaply.
        Index("ix_media_asset_expiry", "status", "expires_at"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    # Server-generated, never client-supplied (§5) — that is what stops one user
    # writing over another's object.
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[MediaStatus] = mapped_column(
        SAEnum(MediaStatus, name="media_status", native_enum=False, length=16),
        default=MediaStatus.PENDING,
        nullable=False,
    )
    visibility: Mapped[MediaVisibility] = mapped_column(
        SAEnum(MediaVisibility, name="media_visibility", native_enum=False, length=16),
        default=MediaVisibility.PRIVATE,
        nullable=False,
    )
    context_type: Mapped[MediaContextType] = mapped_column(
        SAEnum(MediaContextType, name="media_context_type", native_enum=False, length=24),
        nullable=False,
    )
    context_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    # When the object becomes eligible for deletion. Set to a short TTL at upload
    # (abandoned-upload policy) and re-set to resolved_at + retention once a proof is
    # approved or rejected. NULL means "not yet eligible" — a pending-review proof.
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # When the object was actually removed from storage. The row outlives it.
    object_deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class MessageType(enum.StrEnum):
    TEXT = "text"
    SYSTEM = "system"


class GroupMessage(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """Durable chat. Postgres is the source of truth; Redis is transport only (§22)."""

    __tablename__ = "group_message"
    __table_args__ = (Index("ix_group_message_group_created", "group_id", "created_at"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("group.id"), nullable=False
    )
    # Null for system messages — the game emitted them, no person did.
    sender_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[MessageType] = mapped_column(
        SAEnum(MessageType, name="message_type", native_enum=False, length=16),
        default=MessageType.TEXT,
        nullable=False,
    )
    media_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_asset.id"), nullable=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)


class MessageReaction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One emoji per user per message. UNIQUE makes add idempotent structurally rather
    than by convention — a double-tap cannot produce two rows."""

    __tablename__ = "message_reaction"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id", "emoji", name="uq_message_reaction"),
        Index("ix_message_reaction_message", "message_id"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("group_message.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)
