"""Challenge use cases: create, read, edit-pre-start, cancel, and status synchronization.

The status field is never set by a client. `sync_status` is the one place DRAFT→ACTIVE
and ACTIVE→COMPLETED happen, driven by the clock against the challenge's own frozen
timezone, and it runs on every read/write path so a challenge's persisted status is
correct whenever anyone looks at it — no background scheduler needed at V1 scale.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.challenges.challenge_day import challenge_end_at, resolve_challenge_day
from app.domain.challenges.exceptions import (
    ChallengeAlreadyActiveError,
    ChallengeNotFoundError,
    InvalidChallengeConfigError,
    NotAParticipantError,
)
from app.domain.challenges.state_machine import (
    ChallengeState,
    ensure_challenge_transition,
)
from app.models.challenge import (
    ActivityType,
    Challenge,
    ChallengeParticipant,
    ChallengeStatus,
    GameMode,
    VerificationMethod,
)
from app.models.group import Group
from app.repositories.challenges import (
    ChallengeParticipantRepository,
    ChallengeRepository,
)
from app.repositories.groups import GroupMemberRepository

MAX_DURATION_DAYS = 365
MIN_PARTICIPANT_LIMIT = 2

# The column is NUMERIC(12,2). Quantizing on write means a value read back in the same
# response body matches what a later GET returns, instead of "12000" now and "12000.00"
# after a round trip.
_TARGET_PRECISION = Decimal("0.01")


class ChallengeService:
    def __init__(self, session: AsyncSession) -> None:
        self._challenges = ChallengeRepository(session)
        self._participants = ChallengeParticipantRepository(session)
        self._members = GroupMemberRepository(session)

    async def create(
        self,
        *,
        group: Group,
        creator_id: uuid.UUID,
        name: str,
        activity_type: ActivityType,
        target_value: Decimal,
        unit: str,
        game_mode: GameMode,
        verification_method: VerificationMethod,
        duration_days: int,
        participant_limit: int | None,
        start_at: datetime | None,
    ) -> Challenge:
        if duration_days < 1 or duration_days > MAX_DURATION_DAYS:
            raise InvalidChallengeConfigError(
                f"Duration must be between 1 and {MAX_DURATION_DAYS} days."
            )
        if target_value <= 0:
            raise InvalidChallengeConfigError("Daily target must be greater than zero.")
        if participant_limit is not None and participant_limit < MIN_PARTICIPANT_LIMIT:
            raise InvalidChallengeConfigError(
                f"A challenge needs room for at least {MIN_PARTICIPANT_LIMIT} players."
            )

        now = datetime.now(UTC)
        effective_start = start_at or now
        if effective_start < now:
            # A start in the past would mean days that already elapsed with nobody able
            # to complete them — clamped rather than rejected, since "start now" is what
            # the create flow's default means.
            effective_start = now

        # Frozen at creation and never re-read from the group afterwards (Architecture §11).
        timezone = group.timezone
        end_at = challenge_end_at(effective_start, timezone, duration_days)

        challenge = await self._challenges.create(
            group_id=group.id,
            creator_id=creator_id,
            name=name,
            activity_type=activity_type,
            target_value=target_value.quantize(_TARGET_PRECISION),
            unit=unit,
            game_mode=game_mode,
            verification_method=verification_method,
            timezone=timezone,
            start_at=effective_start,
            end_at=end_at,
            duration_days=duration_days,
            participant_limit=participant_limit,
        )
        # The creator is a participant from the start — the design's review step declares
        # war on the creator's own behalf, not as a spectator.
        await self._participants.add(challenge_id=challenge.id, user_id=creator_id)
        await self.sync_status(challenge)
        return challenge

    async def get(self, challenge_id: uuid.UUID) -> Challenge:
        challenge = await self._challenges.get_by_id(challenge_id)
        if challenge is None:
            raise ChallengeNotFoundError(f"No challenge {challenge_id}.")
        await self.sync_status(challenge)
        return challenge

    async def get_for_viewer(
        self, challenge_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[Challenge, ChallengeParticipant | None]:
        """Challenge detail is visible to participants and to any active member of its
        group — the design lets you look at a challenge before joining it.
        """
        challenge = await self.get(challenge_id)
        participant = await self._participants.get(challenge_id, user_id)
        if participant is None and await self._members.get_active(
            challenge.group_id, user_id
        ) is None:
            raise NotAParticipantError("You're not in this challenge or its group.")
        return challenge, participant

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        status: ChallengeStatus | None,
        group_id: uuid.UUID | None,
    ) -> list[tuple[Challenge, ChallengeParticipant]]:
        # Sync before filtering: a challenge whose end_at has passed must appear under
        # COMPLETED on this very request, not on some later one.
        for challenge in await self._challenges.list_stale(datetime.now(UTC)):
            await self.sync_status(challenge)
        return await self._challenges.list_for_user(
            user_id, status=status, group_id=group_id
        )

    async def list_for_group(self, group_id: uuid.UUID) -> list[Challenge]:
        challenges = await self._challenges.list_for_group(group_id)
        for challenge in challenges:
            await self.sync_status(challenge)
        return challenges

    async def update_pre_start(
        self,
        challenge: Challenge,
        *,
        name: str | None,
        target_value: Decimal | None,
    ) -> Challenge:
        await self.sync_status(challenge)
        if challenge.status != ChallengeStatus.DRAFT:
            raise ChallengeAlreadyActiveError(
                "A challenge can only be edited before it starts."
            )
        if name is not None:
            challenge.name = name
        if target_value is not None:
            if target_value <= 0:
                raise InvalidChallengeConfigError("Daily target must be greater than zero.")
            challenge.target_value = target_value.quantize(_TARGET_PRECISION)
        await self._challenges.flush()
        return challenge

    async def cancel(self, challenge: Challenge) -> Challenge:
        """DRAFT → CANCELLED. The only way to reach CANCELLED, and only before start.

        The client asks to cancel an action it owns; it does not name a status. An
        already-running challenge is not cancellable (see `state_machine.py`).
        """
        await self.sync_status(challenge)
        ensure_challenge_transition(
            ChallengeState(challenge.status.value), ChallengeState.CANCELLED
        )
        challenge.status = ChallengeStatus.CANCELLED
        await self._challenges.flush()
        return challenge

    async def sync_status(self, challenge: Challenge, *, now: datetime | None = None) -> None:
        """Advance a challenge's persisted status to match the clock.

        Every transition goes through the domain state machine, so this can never write
        a status the machine forbids — including the CANCELLED case, which the clock
        must never move out of.
        """
        current = datetime.now(UTC) if now is None else now
        state = ChallengeState(challenge.status.value)

        if state is ChallengeState.DRAFT and challenge.start_at <= current:
            ensure_challenge_transition(state, ChallengeState.ACTIVE)
            challenge.status = ChallengeStatus.ACTIVE
            state = ChallengeState.ACTIVE

        if state is ChallengeState.ACTIVE and challenge.end_at <= current:
            ensure_challenge_transition(state, ChallengeState.COMPLETED)
            challenge.status = ChallengeStatus.COMPLETED

        await self._challenges.flush()

    def current_day_index(self, challenge: Challenge, *, now: datetime | None = None) -> int:
        """1-based day number for the UI's "DAY 6 / 30", clamped to the challenge's range."""
        current = datetime.now(UTC) if now is None else now
        start_day = resolve_challenge_day(challenge.start_at, challenge.timezone)
        today = resolve_challenge_day(current, challenge.timezone)
        index = (today - start_day).days + 1
        return max(1, min(index, challenge.duration_days))
