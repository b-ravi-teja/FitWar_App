"""Competitive records: the XP ledger, warnings, and eliminations.

Every table here is append-only and never deleted (Architecture §4.1): they are the
evidentiary record behind "why do I have this much XP" and "why was I eliminated", and
disputes depend on them staying exactly as written.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin


class XPReason(enum.StrEnum):
    """Why XP was granted. V1 is strictly additive — there is no penalty reason,
    because a missed day never writes a ledger row at all (ADR 0002)."""

    DAILY_COMPLETION = "daily_completion"
    STREAK_BONUS = "streak_bonus"
    # Winning a 1v1 (design spec §9 names it in the ledger). Still additive: the loser
    # is not debited, only left unrewarded (ADR 0002, §20.11).
    BATTLE_WIN = "battle_win"


class XPTransaction(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable ledger entry. `UserProfile.xp_total` is a cached projection of the
    sum of these, written in the same transaction (Architecture §3.2).

    Idempotency is structural, not conventional: UNIQUE(user_id, reason, reference_type,
    reference_id) means a replayed verification physically cannot insert a second row for
    the same day's completion, no matter how many requests race.
    """

    __tablename__ = "xp_transaction"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "reason",
            "reference_type",
            "reference_id",
            name="uq_xp_transaction_idempotency",
        ),
        Index("ix_xp_transaction_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    amount: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[XPReason] = mapped_column(
        SAEnum(XPReason, name="xp_reason", native_enum=False, length=32), nullable=False
    )
    # What earned it — `daily_challenge_progress` + that row's id in V1. Kept generic so
    # battle wins and achievements can use the same ledger without a migration.
    reference_type: Mapped[str] = mapped_column(String(48), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)


class Warning(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """A recorded miss counting against a SURVIVAL participant.

    A warning is a state transition, not a UI message. UNIQUE(participant, challenge_day)
    makes a duplicate impossible even if two sweeps resolve the same day at once.
    """

    __tablename__ = "warning"
    __table_args__ = (
        UniqueConstraint(
            "challenge_participant_id", "challenge_day", name="uq_warning_participant_day"
        ),
    )

    challenge_participant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("challenge_participant.id"), nullable=False, index=True
    )
    challenge_day: Mapped[date] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(48), nullable=False)


class Elimination(UUIDPrimaryKeyMixin, Base):
    """A terminal state transition, written once.

    UNIQUE(challenge_participant_id) is the structural guarantee against double
    elimination — and, with `ChallengeParticipant.status`, against resurrection:
    the state machine forbids ELIMINATED → ACTIVE, and this row records that it happened.
    """

    __tablename__ = "elimination"
    __table_args__ = (
        UniqueConstraint("challenge_participant_id", name="uq_elimination_participant"),
    )

    challenge_participant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("challenge_participant.id"), nullable=False
    )
    # The day whose miss triggered it, and the warning that preceded it — the audit
    # trail §3.2 requires for reconstructing an elimination from history.
    challenge_day: Mapped[date] = mapped_column(nullable=False)
    triggered_by_warning_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("warning.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(48), nullable=False)
    eliminated_at: Mapped[datetime] = mapped_column(nullable=False)
