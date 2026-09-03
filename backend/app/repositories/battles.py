"""Persistence for battles.

Locking and constraint handling live here so `BattleService` reads as game rules.
The two operations that matter under concurrency are `lock`, which serializes every
acceptance and finalization of one battle, and `create`, which lets the partial unique
index — not a prior SELECT — decide whether a live battle already exists for a pair.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.battle import (
    Battle,
    BattleParticipant,
    BattleParticipantStatus,
    BattleStatus,
    pair_key,
)
from app.models.challenge import (
    Challenge,
    ChallengeParticipant,
    DailyChallengeProgress,
    DailyProgressStatus,
)
from app.models.game import XPReason, XPTransaction
from app.models.group import GroupMember, GroupMemberStatus
from app.models.user import User, UserProfile

LIVE_STATUSES = (BattleStatus.PENDING, BattleStatus.ACTIVE)

# Must match `services.game_service.BATTLE_REFERENCE` — the ledger's reference type
# for a 1v1 win.
BATTLE_REFERENCE = "battle"


class BattleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get(self, battle_id: uuid.UUID) -> Battle | None:
        result = await self._session.execute(select(Battle).where(Battle.id == battle_id))
        return result.scalar_one_or_none()

    async def lock(self, battle_id: uuid.UUID) -> Battle | None:
        """`SELECT … FOR UPDATE` on the battle row.

        Acceptance and finalization both take this first, which is what makes "two
        concurrent accepts" and "two concurrent finalizations" queue instead of
        interleaving their read-modify-write of the battle's status.

        `populate_existing` is not optional here. The authorization step loads the battle
        before this runs, so without it SQLAlchemy hands back the instance already in the
        identity map with the attributes it had *before* the lock was granted — the lock
        would be taken correctly and then a stale status read through it, which is the
        exact race the lock exists to prevent.
        """
        result = await self._session.execute(
            select(Battle)
            .where(Battle.id == battle_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def participants(self, battle_id: uuid.UUID) -> list[BattleParticipant]:
        result = await self._session.execute(
            select(BattleParticipant)
            .where(BattleParticipant.battle_id == battle_id)
            .order_by(BattleParticipant.slot.asc())
        )
        return list(result.scalars().all())

    async def participants_with_names(
        self, battle_id: uuid.UUID
    ) -> list[tuple[BattleParticipant, str]]:
        result = await self._session.execute(
            select(BattleParticipant, UserProfile.display_name)
            .join(User, User.id == BattleParticipant.user_id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(BattleParticipant.battle_id == battle_id)
            .order_by(BattleParticipant.slot.asc())
        )
        return [(row[0], row[1]) for row in result.all()]

    async def participant_for(
        self, battle_id: uuid.UUID, user_id: uuid.UUID
    ) -> BattleParticipant | None:
        result = await self._session.execute(
            select(BattleParticipant).where(
                BattleParticipant.battle_id == battle_id,
                BattleParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, *, status: BattleStatus | None = None
    ) -> list[Battle]:
        """Every battle the caller is in — the only scope that exists.

        Authorization is the query, not a filter applied after it: a battle the caller
        holds no `BattleParticipant` row for is never selected in the first place.
        """
        stmt = (
            select(Battle)
            .join(BattleParticipant, BattleParticipant.battle_id == Battle.id)
            .where(BattleParticipant.user_id == user_id)
        )
        if status is not None:
            stmt = stmt.where(Battle.status == status)
        result = await self._session.execute(stmt.order_by(Battle.created_at.desc()))
        return list(result.scalars().all())

    async def challenge_for(self, battle: Battle) -> Challenge:
        result = await self._session.execute(
            select(Challenge).where(Challenge.id == battle.challenge_id)
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        challenge_id: uuid.UUID,
        group_id: uuid.UUID,
        creator_id: uuid.UUID,
        opponent_id: uuid.UUID,
        timezone: str,
        start_at: datetime,
        end_at: datetime,
    ) -> Battle | None:
        """Create the battle and both participant rows, or return None if a live battle
        already exists between these two users.

        None comes from `uq_battle_live_pair` rejecting the insert, which is deliberate:
        a check-then-insert would let two simultaneous invitations both pass the check.
        The savepoint keeps the surrounding transaction usable after the rejection.
        """
        battle = Battle(
            challenge_id=challenge_id,
            group_id=group_id,
            creator_id=creator_id,
            status=BattleStatus.PENDING,
            timezone=timezone,
            start_at=start_at,
            end_at=end_at,
            pair_key=pair_key(creator_id, opponent_id),
        )
        try:
            async with self._session.begin_nested():
                self._session.add(battle)
                await self._session.flush()
                # Slot 1 is the challenger, slot 2 the invited opponent. The unique
                # (battle, slot) pair with its CHECK is what caps a battle at two people.
                self._session.add(
                    BattleParticipant(
                        battle_id=battle.id,
                        user_id=creator_id,
                        slot=1,
                        status=BattleParticipantStatus.ACCEPTED,
                        score=Decimal(0),
                    )
                )
                self._session.add(
                    BattleParticipant(
                        battle_id=battle.id,
                        user_id=opponent_id,
                        slot=2,
                        status=BattleParticipantStatus.INVITED,
                        score=Decimal(0),
                    )
                )
                await self._session.flush()
        except IntegrityError:
            return None
        return battle

    async def flush(self) -> None:
        await self._session.flush()

    # ------------------------------------------------------------------
    # Rivals
    # ------------------------------------------------------------------

    async def group_rivals(
        self, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, str]]:
        """Everyone else who is an active member of this group."""
        result = await self._session.execute(
            select(User.id, UserProfile.display_name)
            .join(UserProfile, UserProfile.user_id == User.id)
            .join(GroupMember, GroupMember.user_id == User.id)
            .where(
                GroupMember.group_id == group_id,
                GroupMember.status == GroupMemberStatus.ACTIVE,
                User.id != user_id,
            )
            .order_by(UserProfile.display_name.asc())
        )
        return [(row[0], row[1]) for row in result.all()]

    async def head_to_head(self, user_id: uuid.UUID) -> dict[uuid.UUID, tuple[int, int]]:
        """`{opponent_id: (wins_against, losses_against)}` over completed battles.

        Derived from the persisted `BattleParticipant.status`, never recomputed from
        scores — the result was decided once at finalization and is not re-litigated
        on every read.
        """
        mine = BattleParticipant.__table__.alias("mine")
        theirs = BattleParticipant.__table__.alias("theirs")
        result = await self._session.execute(
            select(theirs.c.user_id, mine.c.status, func.count())
            .select_from(mine)
            .join(theirs, theirs.c.battle_id == mine.c.battle_id)
            .join(Battle, Battle.id == mine.c.battle_id)
            .where(
                mine.c.user_id == user_id,
                theirs.c.user_id != user_id,
                Battle.status == BattleStatus.COMPLETED,
            )
            .group_by(theirs.c.user_id, mine.c.status)
        )
        records: dict[uuid.UUID, tuple[int, int]] = {}
        for opponent_id, status, count in result.all():
            wins, losses = records.get(opponent_id, (0, 0))
            if status == BattleParticipantStatus.WON:
                wins += count
            elif status == BattleParticipantStatus.LOST:
                losses += count
            records[opponent_id] = (wins, losses)
        return records

    async def live_opponents(self, user_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
        """`{opponent_id: battle_id}` for the caller's pending and active battles."""
        mine = BattleParticipant.__table__.alias("mine")
        theirs = BattleParticipant.__table__.alias("theirs")
        result = await self._session.execute(
            select(theirs.c.user_id, Battle.id)
            .select_from(mine)
            .join(theirs, theirs.c.battle_id == mine.c.battle_id)
            .join(Battle, Battle.id == mine.c.battle_id)
            .where(
                mine.c.user_id == user_id,
                theirs.c.user_id != user_id,
                Battle.status.in_(LIVE_STATUSES),
            )
        )
        return {row[0]: row[1] for row in result.all()}

    # ------------------------------------------------------------------
    # Day tallies (read from the challenge machinery — never recomputed)
    # ------------------------------------------------------------------

    async def _day_counts(
        self, challenge_id: uuid.UUID, statuses: tuple[DailyProgressStatus, ...]
    ) -> dict[uuid.UUID, int]:
        result = await self._session.execute(
            select(
                DailyChallengeProgress.challenge_participant_id,
                func.count(),
            )
            .join(
                ChallengeParticipant,
                ChallengeParticipant.id
                == DailyChallengeProgress.challenge_participant_id,
            )
            .where(
                ChallengeParticipant.challenge_id == challenge_id,
                DailyChallengeProgress.status.in_(statuses),
            )
            .group_by(DailyChallengeProgress.challenge_participant_id)
        )
        return {row[0]: row[1] for row in result.all()}

    async def completed_day_counts(self, challenge_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Days each side has actually banked — the "3 / 7 DAYS" the battle screen shows."""
        return await self._day_counts(challenge_id, (DailyProgressStatus.COMPLETED,))

    async def resolved_day_counts(self, challenge_id: uuid.UUID) -> dict[uuid.UUID, int]:
        """Days that can no longer change: completed or missed.

        Once this reaches the battle's duration for both players, the final scores are
        settled and finalization need not wait for the clock.
        """
        return await self._day_counts(
            challenge_id,
            (DailyProgressStatus.COMPLETED, DailyProgressStatus.MISSED),
        )

    async def win_bonus_awarded(
        self, user_id: uuid.UUID, battle_id: uuid.UUID
    ) -> int | None:
        """What the ledger actually recorded for winning this battle, if anything.

        Read from `xp_transaction` rather than restated from the constant, so the
        Victory screen shows what was really paid — if the award were ever missing, the
        screen would say so instead of quietly printing the number it should have been.
        """
        result = await self._session.execute(
            select(XPTransaction.amount).where(
                XPTransaction.user_id == user_id,
                XPTransaction.reason == XPReason.BATTLE_WIN,
                XPTransaction.reference_type == BATTLE_REFERENCE,
                XPTransaction.reference_id == battle_id,
            )
        )
        amount = result.scalar_one_or_none()
        return int(amount) if amount is not None else None

    async def live_battle_ids_for_pair(
        self, a: uuid.UUID, b: uuid.UUID
    ) -> list[uuid.UUID]:
        result = await self._session.execute(
            select(Battle.id).where(
                Battle.pair_key == pair_key(a, b),
                Battle.status.in_(LIVE_STATUSES),
            )
        )
        return list(result.scalars().all())
