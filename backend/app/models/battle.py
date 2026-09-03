"""1v1 battles: the two-player wrapper over a backing 1V1 challenge (Architecture §24).

A battle is **not** a second game engine. The frozen ERD links `BATTLE.challenge_id`,
and §20.3 defines the 1V1 outcome as "mirrored onto both `BattleParticipant.status` and
the linked `ChallengeParticipant.outcome`" — so every battle owns a `Challenge` whose
`game_mode` is `1V1`, and all scoring, day resolution, verification and per-day XP run
through the exact Phase 4/5 machinery that every other challenge uses. What lives here
is only what a head-to-head adds: the invitation, the acceptance, and the final verdict.

Two invariants are enforced by the database rather than by service code, because both
are the kind of thing a race would otherwise break:

- **Exactly two participants.** `slot` is constrained to 1 or 2 and is unique per
  battle, so a third row physically cannot be inserted — no count-then-insert check to
  lose a race.
- **At most one live battle per pair of users.** `pair_key` is the two user ids sorted
  and joined, and a partial unique index covers it only while the battle is `pending` or
  `active`, which is what makes `ALREADY_PENDING_WITH_USER` a constraint rather than a
  best-effort lookup. It is symmetric on purpose: A-invites-B and B-invites-A are the
  same live battle.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CreatedAtMixin, UUIDPrimaryKeyMixin


class BattleStatus(enum.StrEnum):
    """Exactly the states the frozen ERD names — no more.

    There is no `expired`: nothing in the architecture defines an invitation timeout, so
    a pending invitation stays pending until it is accepted or declined.
    """

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class BattleParticipantStatus(enum.StrEnum):
    """Frozen ERD: `invited|accepted|declined|active|won|lost`.

    `accepted` is the instant of consent and `active` the state of playing; in V1 the
    two happen in one transaction, so `accepted` is a transient the acceptance path
    writes through. It is kept because the frozen model names it and because a future
    "both must accept" variant would need it as a resting state.
    """

    INVITED = "invited"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    ACTIVE = "active"
    WON = "won"
    LOST = "lost"


def pair_key(a: uuid.UUID, b: uuid.UUID) -> str:
    """Symmetric key for the two users in a battle — sorted, so who invited whom
    doesn't produce a second "live" battle between the same pair."""
    first, second = sorted((str(a), str(b)))
    return f"{first}:{second}"


_LIVE_STATUS_PREDICATE = "status IN ({})".format(
    ", ".join(f"'{status.name}'" for status in (BattleStatus.PENDING, BattleStatus.ACTIVE))
)


class Battle(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "battle"
    __table_args__ = (
        # One battle per backing challenge, in both directions.
        UniqueConstraint("challenge_id", name="uq_battle_challenge"),
        # The live-battle-per-pair guarantee. Partial, so a completed or cancelled
        # battle never blocks a rematch.
        #
        # The predicate matches on the enum *names*, not the lowercase values the API
        # speaks: SQLAlchemy's `Enum` persists `BattleStatus.PENDING` as "PENDING".
        # Written with a lowercase predicate the index is still created and still
        # unique — it simply never matches a row, and the duplicate it exists to stop
        # sails through. Derived from the members rather than typed out, so renaming a
        # state can't silently disarm it.
        Index(
            "uq_battle_live_pair",
            "pair_key",
            unique=True,
            postgresql_where=text(_LIVE_STATUS_PREDICATE),
        ),
        Index("ix_battle_group_status", "group_id", "status"),
    )

    # The challenge that carries the rules, the days, and the scoring. NOT NULL: a
    # battle without one would need a parallel scoring engine, which §1 forbids.
    challenge_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("challenge.id"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("group.id"), nullable=False
    )
    creator_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False
    )
    status: Mapped[BattleStatus] = mapped_column(
        SAEnum(BattleStatus, name="battle_status", native_enum=False, length=16),
        default=BattleStatus.PENDING,
        nullable=False,
    )
    # Snapshotted from the group at creation and never re-read (§11), exactly as
    # `Challenge.timezone` is.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    # Placeholder while pending; rewritten to the real window the moment the opponent
    # accepts, because that is when the battle actually starts (API_SPEC).
    start_at: Mapped[datetime] = mapped_column(nullable=False)
    end_at: Mapped[datetime] = mapped_column(nullable=False)
    # When finalization actually ran, as opposed to `end_at`, which is only when it
    # became due. Battle history shows this one (§24).
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    pair_key: Mapped[str] = mapped_column(String(80), nullable=False)

    participants: Mapped[list["BattleParticipant"]] = relationship(back_populates="battle")


class BattleParticipant(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "battle_participant"
    __table_args__ = (
        UniqueConstraint("battle_id", "user_id", name="uq_battle_participant_user"),
        # The structural "exactly two" guarantee — see the module docstring.
        UniqueConstraint("battle_id", "slot", name="uq_battle_participant_slot"),
        CheckConstraint("slot IN (1, 2)", name="ck_battle_participant_slot"),
    )

    battle_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("battle.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True
    )
    # 1 = the challenger, 2 = the invited opponent.
    slot: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[BattleParticipantStatus] = mapped_column(
        SAEnum(
            BattleParticipantStatus,
            name="battle_participant_status",
            native_enum=False,
            length=16,
        ),
        default=BattleParticipantStatus.INVITED,
        nullable=False,
    )
    # A projection of the linked `ChallengeParticipant.current_score`, copied at
    # finalization so a completed battle's numbers are readable without re-deriving
    # them — never a client-supplied value, and never the thing scoring is computed on.
    score: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0, nullable=False)

    battle: Mapped["Battle"] = relationship(back_populates="participants")
