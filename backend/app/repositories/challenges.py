import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import (
    ActivityType,
    Challenge,
    ChallengeParticipant,
    ChallengeStatus,
    DailyChallengeProgress,
    DailyProgressStatus,
    GameMode,
    ParticipantStatus,
    VerificationMethod,
)
from app.models.group import GroupMember, GroupMemberStatus
from app.models.user import User, UserProfile


class ChallengeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, challenge_id: uuid.UUID) -> Challenge | None:
        result = await self._session.execute(
            select(Challenge).where(Challenge.id == challenge_id)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        group_id: uuid.UUID,
        creator_id: uuid.UUID,
        name: str,
        activity_type: ActivityType,
        target_value: Decimal,
        unit: str,
        game_mode: GameMode,
        verification_method: VerificationMethod,
        timezone: str,
        start_at: datetime,
        end_at: datetime,
        duration_days: int,
        participant_limit: int | None,
    ) -> Challenge:
        challenge = Challenge(
            group_id=group_id,
            creator_id=creator_id,
            name=name,
            activity_type=activity_type,
            target_value=target_value,
            unit=unit,
            game_mode=game_mode,
            verification_method=verification_method,
            timezone=timezone,
            start_at=start_at,
            end_at=end_at,
            duration_days=duration_days,
            participant_limit=participant_limit,
        )
        self._session.add(challenge)
        await self._session.flush()
        return challenge

    async def list_for_group(
        self, group_id: uuid.UUID, *, status: ChallengeStatus | None = None
    ) -> list[Challenge]:
        stmt = select(Challenge).where(Challenge.group_id == group_id)
        if status is not None:
            stmt = stmt.where(Challenge.status == status)
        result = await self._session.execute(stmt.order_by(Challenge.created_at.desc()))
        return list(result.scalars().all())

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: ChallengeStatus | None = None,
        group_id: uuid.UUID | None = None,
    ) -> list[tuple[Challenge, ChallengeParticipant]]:
        """Challenges the caller participates in, with their own participant row.

        This is `GET /challenges?scope=mine` — the only scope V1 has (ADR 0001, no
        public discovery).
        """
        stmt = (
            select(Challenge, ChallengeParticipant)
            .join(ChallengeParticipant, ChallengeParticipant.challenge_id == Challenge.id)
            .where(ChallengeParticipant.user_id == user_id)
        )
        if status is not None:
            stmt = stmt.where(Challenge.status == status)
        if group_id is not None:
            stmt = stmt.where(Challenge.group_id == group_id)
        result = await self._session.execute(stmt.order_by(Challenge.created_at.desc()))
        return [(row[0], row[1]) for row in result.all()]

    async def list_stale(self, now: datetime) -> list[Challenge]:
        """Challenges whose persisted status has fallen behind the clock.

        Drives the lazy DRAFT→ACTIVE / ACTIVE→COMPLETED sync — see `ChallengeStateService`.
        """
        result = await self._session.execute(
            select(Challenge).where(
                (
                    (Challenge.status == ChallengeStatus.DRAFT)
                    & (Challenge.start_at <= now)
                )
                | ((Challenge.status == ChallengeStatus.ACTIVE) & (Challenge.end_at <= now))
            )
        )
        return list(result.scalars().all())

    async def flush(self) -> None:
        await self._session.flush()


class ChallengeParticipantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, challenge_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChallengeParticipant | None:
        result = await self._session.execute(
            select(ChallengeParticipant).where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, participant_id: uuid.UUID) -> ChallengeParticipant | None:
        result = await self._session.execute(
            select(ChallengeParticipant).where(ChallengeParticipant.id == participant_id)
        )
        return result.scalar_one_or_none()

    async def add(
        self, *, challenge_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChallengeParticipant:
        participant = ChallengeParticipant(challenge_id=challenge_id, user_id=user_id)
        self._session.add(participant)
        await self._session.flush()
        return participant

    async def count_active(self, challenge_id: uuid.UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(ChallengeParticipant)
            .where(
                ChallengeParticipant.challenge_id == challenge_id,
                ChallengeParticipant.status == ParticipantStatus.ACTIVE,
            )
        )
        return result.scalar_one()

    async def list_for_challenge(
        self, challenge_id: uuid.UUID
    ) -> list[tuple[ChallengeParticipant, str]]:
        """Participants with display names, ordered by score then join time.

        Rank is never persisted (Architecture §3.2) — the caller derives it from this
        ordering. Score is 0 for every participant until verification exists (Phase 4),
        so today this effectively orders by join time, which is honest rather than fake.
        """
        stmt = (
            select(ChallengeParticipant, UserProfile.display_name)
            .join(User, User.id == ChallengeParticipant.user_id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(ChallengeParticipant.challenge_id == challenge_id)
            .order_by(
                ChallengeParticipant.current_score.desc(),
                ChallengeParticipant.joined_at.asc(),
            )
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]

    async def active_challenge_ids_for_group_member(
        self, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[uuid.UUID]:
        result = await self._session.execute(
            select(Challenge.id)
            .join(ChallengeParticipant, ChallengeParticipant.challenge_id == Challenge.id)
            .where(
                Challenge.group_id == group_id,
                ChallengeParticipant.user_id == user_id,
                Challenge.status == ChallengeStatus.ACTIVE,
            )
        )
        return list(result.scalars().all())

    async def set_status(
        self, participant: ChallengeParticipant, status: ParticipantStatus
    ) -> ChallengeParticipant:
        participant.status = status
        await self._session.flush()
        return participant


class DailyProgressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, participant_id: uuid.UUID, challenge_day: date
    ) -> DailyChallengeProgress | None:
        result = await self._session.execute(
            select(DailyChallengeProgress).where(
                DailyChallengeProgress.challenge_participant_id == participant_id,
                DailyChallengeProgress.challenge_day == challenge_day,
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create(
        self, participant_id: uuid.UUID, challenge_day: date
    ) -> DailyChallengeProgress:
        """Idempotent by the UNIQUE(participant, day) constraint — a repeat call for the
        same day returns the existing row rather than creating a second one.
        """
        existing = await self.get(participant_id, challenge_day)
        if existing is not None:
            return existing
        progress = DailyChallengeProgress(
            challenge_participant_id=participant_id,
            challenge_day=challenge_day,
            status=DailyProgressStatus.PENDING,
        )
        self._session.add(progress)
        await self._session.flush()
        return progress


class GroupActivityRepository:
    """Reads the group's Feed tab from records Phase 3 already writes.

    Deliberately no `activity` table: an event log is a later phase's concern, and the
    two things that have actually happened in a Phase 3 group — someone joined, someone
    started a challenge — are already persisted with timestamps. This derives the feed
    from those instead of inventing a table or fabricating entries.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def joins(self, group_id: uuid.UUID, limit: int) -> list[tuple[str, datetime]]:
        result = await self._session.execute(
            select(UserProfile.display_name, GroupMember.joined_at)
            .join(User, User.id == GroupMember.user_id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(
                GroupMember.group_id == group_id,
                GroupMember.status == GroupMemberStatus.ACTIVE,
            )
            .order_by(GroupMember.joined_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def challenge_creations(
        self, group_id: uuid.UUID, limit: int
    ) -> list[tuple[str, str, datetime]]:
        result = await self._session.execute(
            select(UserProfile.display_name, Challenge.name, Challenge.created_at)
            .join(User, User.id == Challenge.creator_id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(Challenge.group_id == group_id)
            .order_by(Challenge.created_at.desc())
            .limit(limit)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]
