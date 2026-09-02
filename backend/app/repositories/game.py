"""Persistence for the competitive pipeline.

The locking and constraint handling live here rather than in the service, so the
service reads as game rules and this file carries the concurrency mechanics.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import (
    ChallengeParticipant,
    DailyChallengeProgress,
    DailyProgressStatus,
    ParticipantStatus,
)
from app.models.game import Elimination, Warning, XPTransaction
from app.models.user import User, UserProfile


class GameRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_participant(self, participant_id: uuid.UUID) -> ChallengeParticipant | None:
        """Row-level lock for the duration of the transaction.

        This is the serialization point for the whole competitive pipeline: two requests
        resolving the same participant queue here rather than interleaving their
        read-modify-write of score, streak and miss counters.
        """
        result = await self._session.execute(
            select(ChallengeParticipant)
            .where(ChallengeParticipant.id == participant_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def lock_profile(self, user_id: uuid.UUID) -> UserProfile | None:
        """Locked because `xp_total` is a read-modify-write; without it two concurrent
        awards to the same user could both read the old total and lose one increment."""
        result = await self._session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def completion_already_credited(
        self, user_id: uuid.UUID, progress_id: uuid.UUID
    ) -> bool:
        result = await self._session.execute(
            select(XPTransaction.id).where(
                XPTransaction.user_id == user_id,
                XPTransaction.reference_id == progress_id,
            )
        )
        return result.first() is not None

    async def get_or_create_progress(
        self, participant_id: uuid.UUID, day: date
    ) -> DailyChallengeProgress:
        existing = await self._session.execute(
            select(DailyChallengeProgress).where(
                DailyChallengeProgress.challenge_participant_id == participant_id,
                DailyChallengeProgress.challenge_day == day,
            )
        )
        row = existing.scalar_one_or_none()
        if row is not None:
            return row
        row = DailyChallengeProgress(
            challenge_participant_id=participant_id,
            challenge_day=day,
            status=DailyProgressStatus.PENDING,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def record_warning(
        self, participant_id: uuid.UUID, day: date, *, reason: str
    ) -> Warning | None:
        """Insert a warning, or return the existing one for that day.

        `ON CONFLICT DO NOTHING` against UNIQUE(participant, day) makes this safe under
        concurrency without a pre-check race: two sweeps resolving the same day produce
        one warning, not two.
        """
        statement = (
            pg_insert(Warning)
            .values(
                id=uuid.uuid4(),
                challenge_participant_id=participant_id,
                challenge_day=day,
                reason=reason,
            )
            .on_conflict_do_nothing(constraint="uq_warning_participant_day")
            .returning(Warning.id)
        )
        result = await self._session.execute(statement)
        inserted = result.scalar_one_or_none()
        if inserted is None:
            existing = await self._session.execute(
                select(Warning).where(
                    Warning.challenge_participant_id == participant_id,
                    Warning.challenge_day == day,
                )
            )
            return existing.scalar_one_or_none()
        found = await self._session.execute(select(Warning).where(Warning.id == inserted))
        return found.scalar_one_or_none()

    async def record_elimination(
        self,
        *,
        participant_id: uuid.UUID,
        day: date,
        warning_id: uuid.UUID | None,
        reason: str,
        eliminated_at: datetime,
    ) -> bool:
        """True if this call created the elimination; False if one already existed.

        UNIQUE(challenge_participant_id) is the structural guarantee that a participant
        can be eliminated exactly once, however many resolutions race.
        """
        statement = (
            pg_insert(Elimination)
            .values(
                id=uuid.uuid4(),
                challenge_participant_id=participant_id,
                challenge_day=day,
                triggered_by_warning_id=warning_id,
                reason=reason,
                eliminated_at=eliminated_at,
            )
            .on_conflict_do_nothing(constraint="uq_elimination_participant")
            .returning(Elimination.id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def active_participants(self, challenge_id: uuid.UUID) -> list[ChallengeParticipant]:
        result = await self._session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.status == ParticipantStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

    async def all_participants(self, challenge_id: uuid.UUID) -> list[ChallengeParticipant]:
        result = await self._session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge_id
            )
        )
        return list(result.scalars().all())

    async def participants_with_names(
        self, challenge_id: uuid.UUID
    ) -> list[tuple[ChallengeParticipant, str]]:
        result = await self._session.execute(
            select(ChallengeParticipant, UserProfile.display_name)
            .join(User, User.id == ChallengeParticipant.user_id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(ChallengeParticipant.challenge_id == challenge_id)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def last_completion_times(
        self, challenge_id: uuid.UUID
    ) -> dict[uuid.UUID, datetime]:
        """When each participant's most recent completed day landed — the §20.3
        "reached that score first" tie-break key."""
        result = await self._session.execute(
            select(
                DailyChallengeProgress.challenge_participant_id,
                func.max(DailyChallengeProgress.completed_at),
            )
            .join(
                ChallengeParticipant,
                ChallengeParticipant.id == DailyChallengeProgress.challenge_participant_id,
            )
            .where(
                ChallengeParticipant.challenge_id == challenge_id,
                DailyChallengeProgress.status == DailyProgressStatus.COMPLETED,
            )
            .group_by(DailyChallengeProgress.challenge_participant_id)
        )
        return {row[0]: row[1] for row in result.all() if row[1] is not None}

    async def warnings_for(self, participant_id: uuid.UUID) -> list[Warning]:
        result = await self._session.execute(
            select(Warning)
            .where(Warning.challenge_participant_id == participant_id)
            .order_by(Warning.challenge_day.asc())
        )
        return list(result.scalars().all())

    async def xp_history(
        self, user_id: uuid.UUID, limit: int
    ) -> list[XPTransaction]:
        result = await self._session.execute(
            select(XPTransaction)
            .where(XPTransaction.user_id == user_id)
            .order_by(XPTransaction.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def xp_ledger_total(self, user_id: uuid.UUID) -> int:
        """SUM over the ledger — the reconciliation check against the cached total."""
        result = await self._session.execute(
            select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(
                XPTransaction.user_id == user_id
            )
        )
        return int(result.scalar_one())
