import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    BANNED = "banned"
    DELETED = "deleted"


class OnboardingStage(enum.StrEnum):
    """How far a user has got through first-run onboarding.

    Server-backed rather than a device flag so the answer survives reinstall, a second
    device, and logout/login — the client asks where it left off instead of remembering.
    `COMPLETED` is terminal; the stages before it name the step still to be shown.
    """

    DISCIPLINE = "discipline"
    HEALTH = "health"
    PROFILE = "profile"
    COMPLETED = "completed"


class User(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "user"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="user_status", native_enum=False, length=16),
        default=UserStatus.ACTIVE,
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(nullable=True)

    profile: Mapped["UserProfile"] = relationship(back_populates="user", uselist=False)


class UserProfile(Base):
    __tablename__ = "user_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    # No FK to media_asset yet — that table doesn't exist until the Media phase.
    # See the Phase 1 final report's "deviations" section for why this is a plain
    # column for now rather than a constrained FK.
    avatar_media_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    xp_total: Mapped[int] = mapped_column(default=0, nullable=False)
    notification_preferences: Mapped[dict[str, bool] | None] = mapped_column(JSONB, nullable=True)
    # First-run onboarding progress. Set to DISCIPLINE when a profile is created by
    # registration; accounts that predate this column were backfilled as COMPLETED by the
    # migration, because they already have working accounts and re-onboarding them would
    # be a regression, not a fix.
    onboarding_stage: Mapped[OnboardingStage] = mapped_column(
        SAEnum(OnboardingStage, name="onboarding_stage", native_enum=False, length=16),
        default=OnboardingStage.COMPLETED,
        nullable=False,
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now(), onupdate=lambda: datetime.now(UTC)
    )

    user: Mapped["User"] = relationship(back_populates="profile")
