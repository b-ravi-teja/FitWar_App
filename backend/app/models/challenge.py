import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin


class ActivityType(enum.StrEnum):
    STEPS = "steps"
    ACTIVE_CALORIES = "active_calories"
    DISTANCE = "distance"
    PUSHUPS = "pushups"


class GameMode(enum.StrEnum):
    """V1's three modes (§20.3, design spec §11). TOURNAMENT/TEAM/BOSS are "SOON" chips
    in the design and are deliberately absent from this enum — an unimplemented value
    that the API would accept is worse than one that fails validation.

    `ONE_V_ONE` is not selectable on `POST /groups/{id}/challenges`: a 1v1 challenge is
    the backing record of a `Battle` and is created only through `POST /battles`, so the
    invitation, the two-participant limit and the finalization can't be bypassed by
    driving the challenge API directly.
    """

    SURVIVAL = "survival"
    POINTS = "points"
    ONE_V_ONE = "1v1"


class VerificationMethod(enum.StrEnum):
    APPLE_HEALTH = "apple_health"
    MANUAL_PROOF = "manual_proof"


class ChallengeStatus(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ParticipantStatus(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    LEFT = "left"
    ELIMINATED = "eliminated"


class ParticipantOutcome(enum.StrEnum):
    WON = "won"
    LOST = "lost"
    OUT = "out"
    LEFT = "left"


class DailyProgressStatus(enum.StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    MISSED = "missed"
    EXCUSED = "excused"


class Challenge(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "challenge"
    __table_args__ = (Index("ix_challenge_group_status", "group_id", "status"),)

    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("group.id"), nullable=False
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    activity_type: Mapped[ActivityType] = mapped_column(
        SAEnum(ActivityType, name="activity_type", native_enum=False, length=24), nullable=False
    )
    target_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    game_mode: Mapped[GameMode] = mapped_column(
        SAEnum(GameMode, name="game_mode", native_enum=False, length=16), nullable=False
    )
    verification_method: Mapped[VerificationMethod] = mapped_column(
        SAEnum(VerificationMethod, name="verification_method", native_enum=False, length=24),
        nullable=False,
    )
    status: Mapped[ChallengeStatus] = mapped_column(
        SAEnum(ChallengeStatus, name="challenge_status", native_enum=False, length=16),
        default=ChallengeStatus.DRAFT,
        nullable=False,
    )
    # Snapshotted from Group.timezone at creation and never changed again, even if the
    # group's timezone is later edited (Architecture §11).
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    start_at: Mapped[datetime] = mapped_column(nullable=False)
    end_at: Mapped[datetime] = mapped_column(nullable=False)
    duration_days: Mapped[int] = mapped_column(nullable=False)
    participant_limit: Mapped[int | None] = mapped_column(nullable=True)

    rules: Mapped[list["ChallengeRule"]] = relationship(back_populates="challenge")
    participants: Mapped[list["ChallengeParticipant"]] = relationship(back_populates="challenge")


class ChallengeRule(UUIDPrimaryKeyMixin, Base):
    """Extensible per-mode rule config. V1 writes no rows for the failure rule — that
    threshold is a fixed constant in `domain/challenges/failure_rule.py` (ADR 0004);
    this table exists so making it configurable later needs no migration.
    """

    __tablename__ = "challenge_rule"
    __table_args__ = (
        UniqueConstraint("challenge_id", "rule_key", name="uq_challenge_rule_challenge_key"),
    )

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("challenge.id"), nullable=False
    )
    rule_key: Mapped[str] = mapped_column(String(48), nullable=False)
    rule_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    challenge: Mapped["Challenge"] = relationship(back_populates="rules")


class ChallengeParticipant(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "challenge_participant"
    __table_args__ = (
        UniqueConstraint("challenge_id", "user_id", name="uq_challenge_participant_challenge_user"),
        Index("ix_challenge_participant_user_status", "user_id", "status"),
    )

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("challenge.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    status: Mapped[ParticipantStatus] = mapped_column(
        SAEnum(ParticipantStatus, name="participant_status", native_enum=False, length=16),
        default=ParticipantStatus.ACTIVE,
        nullable=False,
    )
    outcome: Mapped[ParticipantOutcome | None] = mapped_column(
        SAEnum(ParticipantOutcome, name="participant_outcome", native_enum=False, length=16),
        nullable=True,
    )
    current_score: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)
    current_streak: Mapped[int] = mapped_column(default=0, nullable=False)
    longest_streak: Mapped[int] = mapped_column(default=0, nullable=False)
    consecutive_misses: Mapped[int] = mapped_column(default=0, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    eliminated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    challenge: Mapped["Challenge"] = relationship(back_populates="participants")


class DailyChallengeProgress(UUIDPrimaryKeyMixin, Base):
    """One row per participant per challenge-day. Stays PENDING through Phase 3 —
    verification (which resolves it to completed/missed) is Phase 4's job. The shape
    is complete so Phase 4 plugs a VerificationRecord in without touching this table.
    """

    __tablename__ = "daily_challenge_progress"
    __table_args__ = (
        UniqueConstraint(
            "challenge_participant_id", "challenge_day", name="uq_daily_progress_participant_day"
        ),
        Index("ix_daily_progress_challenge_day", "challenge_day"),
    )

    challenge_participant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("challenge_participant.id"), nullable=False
    )
    # Resolved server-side from UTC now + Challenge.timezone. Never client-supplied.
    challenge_day: Mapped[date] = mapped_column(nullable=False)
    status: Mapped[DailyProgressStatus] = mapped_column(
        SAEnum(DailyProgressStatus, name="daily_progress_status", native_enum=False, length=16),
        default=DailyProgressStatus.PENDING,
        nullable=False,
    )
    # The record that resolved this day. Constrained as of Phase 4, now that
    # `verification_record` exists. Nullable while the day is still PENDING, and a day
    # may accumulate several attempt records — this points at the one that decided it.
    # use_alter breaks the circular dependency: verification_record references this
    # table too, so neither can be created with the other's FK already in place.
    verification_record_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("verification_record.id", use_alter=True, name="fk_daily_progress_verification"),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
