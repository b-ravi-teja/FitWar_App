"""The competitive pipeline: score, XP, streak, warning, elimination, finalization.

Everything here runs inside the caller's transaction so a verification either applies
completely or not at all — Architecture §1 tenet 4 and §12's "no silent catch-and-continue
on anything that touches XP/score/elimination".

Concurrency is handled structurally rather than by hoping requests don't overlap:

- The participant row is locked (`SELECT … FOR UPDATE`) before any competitive read or
  write, so two simultaneous resolutions of the same participant serialize.
- `XPTransaction`, `Warning` and `Elimination` each carry a UNIQUE constraint that makes
  a duplicate physically impossible even if a lock is somehow bypassed.
- Every step re-reads state under the lock and no-ops when the work is already done, so
  a replayed request is a read, not a second write.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, EventType, publish
from app.domain.challenges.challenge_day import day_deadline_utc, resolve_challenge_day
from app.domain.challenges.failure_rule import FailureOutcome, evaluate
from app.domain.challenges.failure_rule import Mode as FailureMode
from app.domain.challenges.state_machine import (
    ParticipantState as ParticipantStateMachine,
)
from app.domain.challenges.state_machine import (
    ensure_participant_transition,
)
from app.domain.game import xp_rules
from app.domain.game.standings import (
    Mode,
    ParticipantState,
    Standing,
    points_outcomes,
    rank,
    survival_outcome,
)
from app.models.challenge import (
    Challenge,
    ChallengeParticipant,
    ChallengeStatus,
    DailyChallengeProgress,
    DailyProgressStatus,
    GameMode,
    ParticipantOutcome,
    ParticipantStatus,
)
from app.models.game import XPReason, XPTransaction
from app.models.user import UserProfile
from app.repositories.game import GameRepository

PROGRESS_REFERENCE = "daily_challenge_progress"


class DayResolution:
    """What resolving one day actually did — reported back so the API can tell the user."""

    def __init__(
        self,
        *,
        xp_awarded: int = 0,
        completion_xp: int = 0,
        streak_bonus_xp: int = 0,
        score_delta: Decimal = Decimal(0),
        current_streak: int = 0,
        warning_issued: bool = False,
        eliminated: bool = False,
    ) -> None:
        self.xp_awarded = xp_awarded
        self.completion_xp = completion_xp
        self.streak_bonus_xp = streak_bonus_xp
        self.score_delta = score_delta
        self.current_streak = current_streak
        self.warning_issued = warning_issued
        self.eliminated = eliminated


class GameService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = GameRepository(session)

    # ------------------------------------------------------------------
    # Completion — called by VerificationService when a day is verified
    # ------------------------------------------------------------------

    async def apply_completion(
        self,
        *,
        challenge: Challenge,
        participant: ChallengeParticipant,
        progress: DailyChallengeProgress,
        value: Decimal,
        now: datetime,
    ) -> DayResolution:
        """Credit a completed day: score, streak, XP.

        Idempotent by construction. The XP ledger's UNIQUE key is on
        (user, reason, reference_type, reference_id), so a replay for the same
        `progress.id` cannot insert a second row — and because the row's presence is what
        this checks first, a replay awards nothing and leaves the streak alone.
        """
        locked = await self._repo.lock_participant(participant.id)
        if locked is None:
            return DayResolution(current_streak=participant.current_streak)

        # Already credited? Then this is a replay: report the existing state, change none
        # of it. Checked under the lock so two concurrent replays agree.
        if await self._repo.completion_already_credited(locked.user_id, progress.id):
            return DayResolution(current_streak=locked.current_streak)

        locked.current_streak += 1
        locked.longest_streak = max(locked.longest_streak, locked.current_streak)
        # A completed day clears the warning count — "complete today's mission to reset"
        # (ADR 0004). Warnings already recorded stay; they are history, not a live tally.
        locked.consecutive_misses = 0
        locked.current_score = Decimal(locked.current_score) + value

        completion = xp_rules.completion_xp()
        bonus = xp_rules.streak_bonus_xp(locked.current_streak)
        await self._award_xp(
            user_id=locked.user_id,
            progress_id=progress.id,
            completion=completion,
            bonus=bonus,
        )

        await self._session.flush()

        self._publish_after_commit(
            EventType.SCORE_CHANGED,
            challenge_id=challenge.id,
            user_id=locked.user_id,
            payload={"score": str(locked.current_score), "streak": locked.current_streak},
        )
        return DayResolution(
            xp_awarded=completion + bonus,
            completion_xp=completion,
            streak_bonus_xp=bonus,
            score_delta=value,
            current_streak=locked.current_streak,
        )

    async def _award_xp(
        self, *, user_id: uuid.UUID, progress_id: uuid.UUID, completion: int, bonus: int
    ) -> None:
        """Ledger rows plus the cached total, in one transaction (Architecture §3.2).

        `xp_total` is never written independently of a ledger row — that invariant is
        what makes the nightly SUM reconciliation meaningful.
        """
        granted = 0
        for reason, amount in (
            (XPReason.DAILY_COMPLETION, completion),
            (XPReason.STREAK_BONUS, bonus),
        ):
            if amount <= 0:
                continue
            self._session.add(
                XPTransaction(
                    user_id=user_id,
                    amount=amount,
                    reason=reason,
                    reference_type=PROGRESS_REFERENCE,
                    reference_id=progress_id,
                )
            )
            granted += amount

        if granted:
            profile = await self._repo.lock_profile(user_id)
            if profile is not None:
                profile.xp_total += granted
            self._publish_after_commit(
                EventType.XP_AWARDED, user_id=user_id, payload={"amount": granted}
            )

    # ------------------------------------------------------------------
    # Deadline resolution — the sweep §20.5 requires
    # ------------------------------------------------------------------

    async def resolve_overdue_days(
        self, challenge: Challenge, *, now: datetime | None = None
    ) -> int:
        """Resolve every day whose deadline has passed with no verified completion.

        §20.5 requires resolution to be deadline-driven so failure-rule timing stays
        deterministic and never waits on a human or a client. No scheduler exists in the
        repository, and inventing one is out of scope, so this runs **lazily**: any read
        or write that touches a challenge sweeps it first. The effect is the same — a day
        cannot be observed unresolved after its deadline — and the operation is idempotent,
        so a future cron calling it changes nothing.

        Returns the number of days newly resolved.
        """
        now = now or datetime.now(UTC)
        if challenge.status not in (ChallengeStatus.ACTIVE, ChallengeStatus.COMPLETED):
            return 0

        start_day = resolve_challenge_day(challenge.start_at, challenge.timezone)
        today = resolve_challenge_day(now, challenge.timezone)
        resolved = 0

        for participant in await self._repo.active_participants(challenge.id):
            for day_offset in range(challenge.duration_days):
                day = date.fromordinal(start_day.toordinal() + day_offset)
                if day >= today or day_deadline_utc(day, challenge.timezone) > now:
                    continue
                if await self._resolve_missed_day(challenge, participant, day, now):
                    resolved += 1
        return resolved

    async def _resolve_missed_day(
        self,
        challenge: Challenge,
        participant: ChallengeParticipant,
        day: date,
        now: datetime,
    ) -> bool:
        locked = await self._repo.lock_participant(participant.id)
        if locked is None or locked.status is not ParticipantStatus.ACTIVE:
            # Already eliminated or departed — there is no open day left to miss, and
            # resolving one would be the resurrection path the rules forbid.
            return False

        progress = await self._repo.get_or_create_progress(locked.id, day)
        # Only a still-pending day can become missed. COMPLETED stays completed (late
        # evidence never rewrites it) and MISSED is already resolved — this is what makes
        # a second sweep a no-op rather than a second warning.
        if progress.status is not DailyProgressStatus.PENDING:
            return False

        progress.status = DailyProgressStatus.MISSED
        locked.current_streak = 0
        locked.consecutive_misses += 1

        if challenge.game_mode is GameMode.SURVIVAL:
            await self._apply_failure_rule(challenge, locked, day, now)

        await self._session.flush()
        return True

    async def _apply_failure_rule(
        self,
        challenge: Challenge,
        participant: ChallengeParticipant,
        day: date,
        now: datetime,
    ) -> None:
        outcome = evaluate(FailureMode.SURVIVAL, participant.consecutive_misses)
        if outcome is FailureOutcome.NONE:
            return

        warning = await self._repo.record_warning(participant.id, day, reason="missed_day")
        if warning is not None:
            self._publish_after_commit(
                EventType.WARNING_ISSUED,
                challenge_id=challenge.id,
                user_id=participant.user_id,
                payload={"challenge_day": day.isoformat()},
            )

        if outcome is not FailureOutcome.ELIMINATED:
            return

        # ACTIVE → ELIMINATED goes through the state machine, so an illegal transition
        # (e.g. from an already-terminal state) raises rather than silently writing.
        ensure_participant_transition(
            ParticipantStateMachine(participant.status.value), ParticipantStateMachine.ELIMINATED
        )
        created = await self._repo.record_elimination(
            participant_id=participant.id,
            day=day,
            warning_id=warning.id if warning else None,
            reason="consecutive_misses",
            eliminated_at=now,
        )
        if not created:
            return

        participant.status = ParticipantStatus.ELIMINATED
        participant.outcome = ParticipantOutcome.OUT
        participant.eliminated_at = now
        self._publish_after_commit(
            EventType.PARTICIPANT_ELIMINATED,
            challenge_id=challenge.id,
            user_id=participant.user_id,
            payload={"challenge_day": day.isoformat()},
        )

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    async def finalize_if_ended(
        self, challenge: Challenge, *, now: datetime | None = None
    ) -> bool:
        """Close a challenge past its end: resolve outstanding days, then write outcomes.

        Idempotent — a participant whose `outcome` is already set is never rewritten,
        which is also what makes standings immutable after close (§3.2: outcome is
        written once and is final).
        """
        now = now or datetime.now(UTC)
        if challenge.status is not ChallengeStatus.COMPLETED or challenge.end_at > now:
            return False

        # Days that expired before the challenge closed still count as misses.
        await self.resolve_overdue_days(challenge, now=now)

        participants = await self._repo.all_participants(challenge.id)
        pending = [p for p in participants if p.outcome is None]
        if not pending:
            return False

        standings = await self._standings(challenge, participants)
        by_id = {s.participant_id: s for s in standings}

        if challenge.game_mode is GameMode.SURVIVAL:
            for participant in pending:
                standing = by_id[participant.id]
                participant.outcome = ParticipantOutcome(survival_outcome(standing.state).value)
        else:
            outcomes = points_outcomes(standings)
            for participant in pending:
                participant.outcome = ParticipantOutcome(outcomes[participant.id].value)

        # Everyone still standing has finished; the state machine keeps this honest.
        for participant in pending:
            if participant.status is ParticipantStatus.ACTIVE:
                ensure_participant_transition(
                    ParticipantStateMachine.ACTIVE, ParticipantStateMachine.COMPLETED
                )
                participant.status = ParticipantStatus.COMPLETED

        await self._session.flush()
        self._publish_after_commit(
            EventType.CHALLENGE_COMPLETED, challenge_id=challenge.id, payload={}
        )
        return True

    # ------------------------------------------------------------------
    # Standings / leaderboard
    # ------------------------------------------------------------------

    async def _standings(
        self, challenge: Challenge, participants: list[ChallengeParticipant]
    ) -> list[Standing]:
        reached = await self._repo.last_completion_times(challenge.id)
        return [
            Standing(
                participant_id=p.id,
                user_id=p.user_id,
                score=Decimal(p.current_score),
                reached_score_at=reached.get(p.id),
                current_streak=p.current_streak,
                joined_at=p.joined_at,
                state=ParticipantState(p.status.value),
            )
            for p in participants
        ]

    async def leaderboard(
        self, challenge: Challenge, *, now: datetime | None = None
    ) -> list[tuple[int, ChallengeParticipant, str]]:
        """Ranked standings, computed at read time and never persisted (§3.2).

        Sweeps overdue days first so a leaderboard read can't show a stale "still in it"
        for someone whose deadline passed hours ago.
        """
        now = now or datetime.now(UTC)
        await self.resolve_overdue_days(challenge, now=now)
        await self.finalize_if_ended(challenge, now=now)

        rows = await self._repo.participants_with_names(challenge.id)
        by_id = {p.id: (p, name) for p, name in rows}
        standings = await self._standings(challenge, [p for p, _ in rows])
        return [(position, *by_id[s.participant_id]) for position, s in rank(standings)]

    def mode(self, challenge: Challenge) -> Mode:
        return Mode(challenge.game_mode.value)

    # ------------------------------------------------------------------

    def _publish_after_commit(
        self,
        event_type: EventType,
        *,
        challenge_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        """Queue an event to fire once this transaction commits.

        Publishing inline would let a subscriber observe a score change that a later
        rollback erases; SQLAlchemy's `after_commit` hook is what keeps the two honest.
        """
        event = DomainEvent(
            type=event_type,
            challenge_id=challenge_id,
            user_id=user_id,
            occurred_at=datetime.now(UTC),
            payload=dict(payload or {}),
        )
        session = self._session

        def _emit(_: object) -> None:
            publish(event)

        from sqlalchemy import event as sa_event

        sa_event.listen(session.sync_session, "after_commit", _emit, once=True)


async def xp_summary(session: AsyncSession, user_id: uuid.UUID) -> tuple[int, int, int, int]:
    """(xp_total, level, xp_into_level, xp_to_next_level) from the cached total."""
    result = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
    profile = result.scalar_one()
    total = profile.xp_total
    return (
        total,
        xp_rules.level_for_xp(total),
        xp_rules.xp_into_level(total),
        xp_rules.xp_to_next_level(total),
    )
