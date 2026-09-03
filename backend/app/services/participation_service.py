"""Join/leave a challenge, and read a participant's daily progress.

Every "can I?" answer is decided here against server state — the client sends an action,
never a resulting status (Architecture §1, tenet 1).
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.challenges.challenge_day import (
    day_deadline_utc,
    is_within_challenge,
    resolve_challenge_day,
)
from app.domain.challenges.exceptions import (
    AlreadyJoinedError,
    CannotRejoinError,
    ChallengeAlreadyEndedError,
    ChallengeNotActiveError,
    InvalidDayError,
    NotAParticipantError,
    ParticipantLimitReachedError,
)
from app.domain.challenges.state_machine import (
    ParticipantState,
    ensure_participant_transition,
)
from app.domain.groups.exceptions import NotAGroupMemberError
from app.models.challenge import (
    Challenge,
    ChallengeParticipant,
    ChallengeStatus,
    DailyChallengeProgress,
    ParticipantOutcome,
    ParticipantStatus,
)
from app.repositories.challenges import (
    ChallengeParticipantRepository,
    ChallengeRepository,
    DailyProgressRepository,
)
from app.repositories.groups import GroupMemberRepository


class ParticipationService:
    def __init__(self, session: AsyncSession) -> None:
        self._challenges = ChallengeRepository(session)
        self._participants = ChallengeParticipantRepository(session)
        self._progress = DailyProgressRepository(session)
        self._members = GroupMemberRepository(session)

    async def list_participants(
        self, challenge_id: uuid.UUID
    ) -> list[tuple[ChallengeParticipant, str]]:
        return await self._participants.list_for_challenge(challenge_id)

    async def require_participant(
        self, challenge_id: uuid.UUID, user_id: uuid.UUID
    ) -> ChallengeParticipant:
        participant = await self._participants.get(challenge_id, user_id)
        if participant is None:
            raise NotAParticipantError("You haven't joined this challenge.")
        return participant

    async def join(
        self, *, challenge: Challenge, user_id: uuid.UUID
    ) -> ChallengeParticipant:
        if await self._members.get_active(challenge.group_id, user_id) is None:
            raise NotAGroupMemberError("Join the group before joining its challenges.")

        # Serialize joins to this challenge. Everything below is a read-then-write
        # against shared state — the participant limit especially — and concurrent
        # joiners would otherwise all observe the same pre-insert count and all be
        # admitted. `UNIQUE(challenge_id, user_id)` still covers the duplicate-self case;
        # this covers the capacity case, which no constraint can express.
        await self._challenges.lock(challenge.id)

        if challenge.status in (ChallengeStatus.COMPLETED, ChallengeStatus.CANCELLED):
            raise ChallengeAlreadyEndedError("This challenge is over.")

        existing = await self._participants.get(challenge.id, user_id)
        if existing is not None:
            if existing.status == ParticipantStatus.ACTIVE:
                raise AlreadyJoinedError("You're already in this challenge.")
            # LEFT, ELIMINATED and COMPLETED are terminal (Architecture §3.3). Reviving
            # one would make elimination meaningless in SURVIVAL and would let someone
            # re-enter a challenge they already finished.
            raise CannotRejoinError(
                "You can't re-enter a challenge you already left, finished, or were "
                "eliminated from."
            )

        if challenge.participant_limit is not None:
            active = await self._participants.count_active(challenge.id)
            if active >= challenge.participant_limit:
                raise ParticipantLimitReachedError("This challenge is full.")

        return await self._participants.add(challenge_id=challenge.id, user_id=user_id)

    async def leave(self, *, challenge: Challenge, participant: ChallengeParticipant) -> None:
        if challenge.status in (ChallengeStatus.COMPLETED, ChallengeStatus.CANCELLED):
            raise ChallengeAlreadyEndedError(
                "This challenge has already ended — there's nothing to leave."
            )
        ensure_participant_transition(
            ParticipantState(participant.status.value), ParticipantState.LEFT
        )
        # `outcome` is written once and is final (Architecture §3.2); leaving is already
        # a terminal event, so it's decided here rather than at challenge close.
        participant.outcome = ParticipantOutcome.LEFT
        await self._participants.set_status(participant, ParticipantStatus.LEFT)

    async def progress_for_today(
        self, *, challenge: Challenge, participant: ChallengeParticipant
    ) -> tuple[DailyChallengeProgress, date, datetime]:
        """Today's progress row, created PENDING if this is the first look at the day.

        "Today" is resolved from the challenge's frozen timezone, never from anything the
        client sent. Creating the row here is safe and idempotent — UNIQUE(participant,
        challenge_day) means a concurrent duplicate request can't produce two rows.
        """
        if challenge.status != ChallengeStatus.ACTIVE:
            raise ChallengeNotActiveError(
                f"Challenge is '{challenge.status.value}' and has no active day."
            )
        today = resolve_challenge_day(datetime.now(UTC), challenge.timezone)
        progress = await self._progress.get_or_create(participant.id, today)
        deadline = day_deadline_utc(today, challenge.timezone)
        return progress, today, deadline

    async def progress_for_date(
        self, *, challenge: Challenge, participant: ChallengeParticipant, day: date
    ) -> tuple[DailyChallengeProgress, datetime]:
        """A historical day, read-only.

        Unlike `/today` this never creates a row: back-filling a day that was never
        looked at would invent a record of a day the participant may not have been in
        the challenge for.
        """
        start_day = resolve_challenge_day(challenge.start_at, challenge.timezone)
        if not is_within_challenge(day, start_day, challenge.duration_days):
            raise InvalidDayError(f"{day.isoformat()} is outside this challenge's range.")
        progress = await self._progress.get(participant.id, day)
        if progress is None:
            raise InvalidDayError(f"No progress recorded for {day.isoformat()}.")
        return progress, day_deadline_utc(day, challenge.timezone)
