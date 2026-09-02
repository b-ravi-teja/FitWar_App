"""Health connections and verification records (Architecture §3.1, §4 ERD)."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin


class HealthProvider(enum.StrEnum):
    """Sources a user can link. `health_connect` is the Android counterpart the
    architecture reserves room for (§1); it is not implemented on iOS."""

    APPLE_HEALTH = "apple_health"
    HEALTH_CONNECT = "health_connect"


class HealthConnectionStatus(enum.StrEnum):
    CONNECTED = "connected"
    REVOKED = "revoked"


class VerificationStatus(enum.StrEnum):
    VERIFIED = "verified"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class HealthConnection(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A user's link to an external health source. Not tied to a challenge (§3.1).

    Stores no health data and no HealthKit objects — only the fact that a link exists.
    HealthKit grants no way to read back authorization state for *read* scopes anyway
    (Apple deliberately hides it so apps cannot detect a refusal), so this records the
    user's intent to connect plus the server's own observation of when evidence last
    actually arrived. The latter is the honest signal that the link works.
    """

    __tablename__ = "health_connection"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_health_connection_user_provider"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True
    )
    provider: Mapped[HealthProvider] = mapped_column(
        SAEnum(HealthProvider, name="health_provider", native_enum=False, length=24),
        nullable=False,
    )
    status: Mapped[HealthConnectionStatus] = mapped_column(
        SAEnum(
            HealthConnectionStatus,
            name="health_connection_status",
            native_enum=False,
            length=16,
        ),
        default=HealthConnectionStatus.CONNECTED,
        nullable=False,
    )
    # Set by the server when a submission actually succeeds — never client-asserted.
    last_synced_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class VerificationRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One verification attempt's normalized outcome.

    Immutable once written (§3.2): it is the evidentiary record of what a provider
    decided at a moment in time, and disputes ("why wasn't my day counted?") depend on
    it staying exactly as recorded. A later attempt writes a new row rather than
    editing this one — which is also what lets a rejected day be retried.
    """

    __tablename__ = "verification_record"
    __table_args__ = (
        Index("ix_verification_record_status", "status"),
        Index("ix_verification_record_progress", "daily_challenge_progress_id"),
    )

    daily_challenge_progress_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("daily_challenge_progress.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    # Unit is folded into the name ("distance_km") — see domain/verification/metrics.py.
    metric: Mapped[str] = mapped_column(String(48), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    target: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, name="verification_status", native_enum=False, length=20),
        nullable=False,
    )
    # Stable code explaining a non-verified outcome (TARGET_NOT_MET, USER_ENTERED_DATA,
    # OUTSIDE_CHALLENGE_DAY, ...). Null when verified.
    reason_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    # When the activity happened, not when it was submitted.
    source_timestamp: Mapped[datetime] = mapped_column(nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(nullable=True)
    # No FK — `media_asset` doesn't exist until the Media phase, same treatment as
    # UserProfile.avatar_media_id.
    evidence_media_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    # Manual-proof review fields (§20.5). Unused until that phase, present because the
    # frozen ERD defines them on this table.
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The normalized submission exactly as received, for audit and dispute resolution.
    # Normalized evidence only — never raw HealthKit objects (§8 boundary).
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
