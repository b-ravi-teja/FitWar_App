"""1v1 battle use cases: invite, accept, decline, verify, finalize (Architecture §24).

The shape of this file is the point of Phase 7: it is short because a battle is a
two-player *arrangement* around machinery that already exists. Every competitive number
comes from somewhere else —

    evidence → VerificationProvider → VerificationRecord → DailyChallengeProgress
             → GameService.apply_completion (score, streak, per-day XP)
             → standings.rank_key (the frozen §20.3 five-step tie-break)
             → standings.points_outcomes (exactly one WON)
             → GameService.award_battle_win_xp (the same ledger)

— and nothing here recomputes any of it. There is no battle scoring algorithm, no
battle tie-break, no battle XP system, and no HealthKit anywhere near this module.

Concurrency is handled by taking the battle row's lock before any state decision, and by
constraints that make the bad state unrepresentable rather than merely unlikely:
`uq_battle_participant_slot` (never a third player), `uq_battle_live_pair` (never two
live battles for one pair), `uq_challenge_participant_challenge_user` (never a duplicate
entrant), and `uq_xp_transaction_idempotency` (never a second win bonus).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.realtime import battle_channel, group_channel, publish_realtime
from app.domain.battles.exceptions import (
    AlreadyPendingWithUserError,
    BattleNotActiveError,
    BattleNotFoundError,
    BattleNotPendingError,
    GroupRequiredError,
    NotABattleParticipantError,
    NotInvitedError,
    OpponentNotAvailableError,
)
from app.domain.battles.rules import (
    default_target,
    validate_activity,
    validate_duration,
    validate_target,
)
from app.domain.challenges.challenge_day import challenge_end_at, resolve_challenge_day
from app.domain.challenges.state_machine import (
    ChallengeState,
    ensure_challenge_transition,
    ensure_participant_transition,
)
from app.domain.challenges.state_machine import (
    ParticipantState as ParticipantStateMachine,
)
from app.domain.game.standings import Outcome, points_outcomes
from app.domain.verification.evidence import HealthEvidence
from app.domain.verification.metrics import CANONICAL_UNIT, ActivityKind
from app.models.battle import (
    Battle,
    BattleParticipant,
    BattleParticipantStatus,
    BattleStatus,
)
from app.models.challenge import (
    ActivityType,
    Challenge,
    ChallengeParticipant,
    ChallengeStatus,
    GameMode,
    ParticipantOutcome,
    ParticipantStatus,
    VerificationMethod,
)
from app.models.group import Group
from app.repositories.battles import BattleRepository
from app.repositories.challenges import ChallengeParticipantRepository, ChallengeRepository
from app.repositories.game import GameRepository
from app.repositories.groups import GroupMemberRepository, GroupRepository
from app.repositories.users import UserRepository
from app.services.game_service import GameService
from app.services.verification_service import VerificationOutcome, VerificationService

logger = get_logger(__name__)

_TARGET_PRECISION = Decimal("0.01")

# Battles verify automatically in V1 — see `domain/battles/rules.validate_activity`
# and ADR 0009.
BATTLE_VERIFICATION_METHOD = VerificationMethod.APPLE_HEALTH


@dataclass(frozen=True)
class BattleSide:
    """One player as the battle screen shows them.

    Deliberately narrow (§18): a display name, a score, how many days they have banked,
    and their status. No evidence, no media, no verification record, no health data —
    the opponent sees the contest, never the other player's private record.
    """

    user_id: uuid.UUID
    display_name: str
    status: BattleParticipantStatus
    score: Decimal
    days_completed: int
    is_me: bool


@dataclass(frozen=True)
class BattleView:
    battle: Battle
    challenge: Challenge
    sides: list[BattleSide]
    day_index: int
    my_outcome: Outcome | None
    winner_user_id: uuid.UUID | None
    # What the XP ledger actually paid the viewer for winning, read back rather than
    # restated from the constant. `None` for the loser and for an unfinished battle.
    my_xp_awarded: int | None


class BattleService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._battles = BattleRepository(session)
        self._challenges = ChallengeRepository(session)
        self._participants = ChallengeParticipantRepository(session)
        self._members = GroupMemberRepository(session)
        self._groups = GroupRepository(session)
        self._users = UserRepository(session)
        self._game = GameService(session)
        self._game_repo = GameRepository(session)
        self._verification = VerificationService(session)

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    async def create(
        self,
        *,
        creator_id: uuid.UUID,
        opponent_user_id: uuid.UUID,
        activity_type: ActivityType,
        target_value: Decimal | None,
        duration_days: int,
        group_id: uuid.UUID | None,
        now: datetime | None = None,
    ) -> Battle:
        """Invite one opponent to a head-to-head. The battle starts when they accept."""
        now = now or datetime.now(UTC)
        activity = ActivityKind(activity_type.value)
        validate_activity(activity)
        validate_duration(duration_days)
        target = (target_value if target_value is not None else default_target(activity))
        validate_target(target)

        if opponent_user_id == creator_id:
            raise OpponentNotAvailableError("You can't battle yourself.")

        group = await self._resolve_group(creator_id, opponent_user_id, group_id)

        # The backing challenge carries every rule the battle plays by. It is created
        # DRAFT with a placeholder window: nothing starts until the invitation is
        # accepted, and no clock sweep can touch it because 1v1 challenges are excluded
        # from every challenge listing (`repositories/challenges._NOT_A_BATTLE`).
        timezone = group.timezone
        challenge = await self._challenges.create(
            group_id=group.id,
            creator_id=creator_id,
            name="1V1 BATTLE",
            activity_type=activity_type,
            target_value=target.quantize(_TARGET_PRECISION),
            unit=CANONICAL_UNIT[activity],
            game_mode=GameMode.ONE_V_ONE,
            verification_method=BATTLE_VERIFICATION_METHOD,
            timezone=timezone,
            start_at=now,
            end_at=challenge_end_at(now, timezone, duration_days),
            duration_days=duration_days,
            # Belt and braces on top of the slot constraint: even the challenge behind
            # the battle refuses a third entrant.
            participant_limit=2,
        )
        # The challenger is in from the moment they declare — which is also what makes
        # their `joined_at` earlier than their opponent's, the fourth tie-break key.
        await self._participants.add(challenge_id=challenge.id, user_id=creator_id)

        battle = await self._battles.create(
            challenge_id=challenge.id,
            group_id=group.id,
            creator_id=creator_id,
            opponent_id=opponent_user_id,
            timezone=timezone,
            start_at=now,
            end_at=challenge.end_at,
        )
        if battle is None:
            # `uq_battle_live_pair` rejected it: these two already have a battle running
            # or an invitation outstanding.
            raise AlreadyPendingWithUserError(
                "You already have a battle running with this player."
            )

        await self._session.flush()
        await self._publish(
            group_channel(group.id),
            "battle_invited",
            battle,
            extra={"opponent_user_id": str(opponent_user_id)},
        )
        return battle

    async def _resolve_group(
        self, creator_id: uuid.UUID, opponent_id: uuid.UUID, group_id: uuid.UUID | None
    ) -> Group:
        """Which squad hosts this battle.

        The frozen rival list is group-scoped (`GET /battles/rivals?group_id=`), so the
        product rule is "you may challenge someone you share a squad with". `group_id` is
        optional on the request and inferred when there is exactly one candidate; several
        shared groups is genuinely ambiguous and asks rather than guesses.

        Every failure below raises the *same* error, so this cannot be used to learn
        whether an account exists or which squads someone is in.
        """
        if group_id is not None:
            group = await self._groups.get_by_id(group_id)
            if group is None:
                raise OpponentNotAvailableError("You can't battle that player.")
            mine = await self._members.get_active(group_id, creator_id)
            theirs = await self._members.get_active(group_id, opponent_id)
            if mine is None or theirs is None:
                raise OpponentNotAvailableError("You can't battle that player.")
            return group

        shared = await self._members.shared_group_ids(creator_id, opponent_id)
        if not shared:
            raise OpponentNotAvailableError("You can't battle that player.")
        if len(shared) > 1:
            raise GroupRequiredError(
                "You share more than one squad with this player — say which one."
            )
        group = await self._groups.get_by_id(shared[0])
        if group is None:  # pragma: no cover - referential integrity
            raise OpponentNotAvailableError("You can't battle that player.")
        return group

    # ------------------------------------------------------------------
    # Authorization
    # ------------------------------------------------------------------

    async def get_for_participant(
        self, battle_id: uuid.UUID, user_id: uuid.UUID
    ) -> tuple[Battle, BattleParticipant]:
        """Load a battle the caller actually plays in.

        A non-participant gets `BATTLE_NOT_FOUND`, identical to a made-up id: §12 says
        the existence of a private battle must not leak, and ids are not secrets.
        """
        battle = await self._battles.get(battle_id)
        if battle is None:
            raise BattleNotFoundError(f"No battle {battle_id}.")
        participant = await self._battles.participant_for(battle_id, user_id)
        if participant is None:
            raise BattleNotFoundError(f"No battle {battle_id}.")
        return battle, participant

    async def is_participant(self, battle_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        return await self._battles.participant_for(battle_id, user_id) is not None

    # ------------------------------------------------------------------
    # Invitation lifecycle
    # ------------------------------------------------------------------

    async def accept(self, battle_id: uuid.UUID, user_id: uuid.UUID) -> Battle:
        """The invited opponent accepts; the battle starts now.

        Idempotent and race-safe. The battle row is locked first, so two simultaneous
        accepts serialize: the first flips PENDING → ACTIVE, the second finds it already
        ACTIVE and returns the same battle instead of starting a second one. Even if the
        lock were bypassed, `uq_challenge_participant_challenge_user` would refuse the
        duplicate entrant.
        """
        await self.get_for_participant(battle_id, user_id)
        locked = await self._battles.lock(battle_id)
        if locked is None:  # pragma: no cover - deleted mid-request
            raise BattleNotFoundError(f"No battle {battle_id}.")

        # Re-read the participant *under the lock*: the pre-lock read above only
        # established authorization, and the row may have moved since.
        mine = await self._battles.participant_for(battle_id, user_id)
        if mine is None:  # pragma: no cover - guarded above
            raise BattleNotFoundError(f"No battle {battle_id}.")
        if mine.status is BattleParticipantStatus.DECLINED:
            raise NotInvitedError("You already declined this battle.")
        if locked.status is BattleStatus.CANCELLED:
            raise NotInvitedError("This battle was cancelled.")
        if locked.status in (BattleStatus.ACTIVE, BattleStatus.COMPLETED):
            if mine.slot == 2:
                # The replay of a successful accept — the same answer, no second write.
                return locked
            raise BattleNotPendingError("This battle has already started.")
        if mine.slot != 2:
            # The challenger is already in; only the invited opponent accepts.
            raise NotInvitedError("You aren't the invited player in this battle.")

        challenge = await self._battles.challenge_for(locked)
        now = datetime.now(UTC)
        end_at = challenge_end_at(now, locked.timezone, challenge.duration_days)

        await self._participants.add(challenge_id=challenge.id, user_id=user_id)

        ensure_challenge_transition(
            ChallengeState(challenge.status.value), ChallengeState.ACTIVE
        )
        challenge.status = ChallengeStatus.ACTIVE
        challenge.start_at = now
        challenge.end_at = end_at

        locked.status = BattleStatus.ACTIVE
        locked.start_at = now
        locked.end_at = end_at
        for participant in await self._battles.participants(battle_id):
            participant.status = BattleParticipantStatus.ACTIVE

        await self._session.flush()
        await self._publish(battle_channel(battle_id), "battle_status_changed", locked)
        await self._publish(group_channel(locked.group_id), "battle_status_changed", locked)
        return locked

    async def decline(self, battle_id: uuid.UUID, user_id: uuid.UUID) -> Battle:
        """The invited opponent refuses; the battle is cancelled and never ran.

        No outcome is written on either side. `LEFT` in §20.3 describes forfeiting a
        contest that started — a declined invitation started nothing, so recording a
        result for it would be a fabricated match in both players' history.
        """
        await self.get_for_participant(battle_id, user_id)
        locked = await self._battles.lock(battle_id)
        if locked is None:  # pragma: no cover - deleted mid-request
            raise BattleNotFoundError(f"No battle {battle_id}.")

        mine = await self._battles.participant_for(battle_id, user_id)
        if mine is None:  # pragma: no cover - guarded above
            raise BattleNotFoundError(f"No battle {battle_id}.")
        if locked.status is BattleStatus.CANCELLED:
            return locked  # idempotent replay
        if locked.status is not BattleStatus.PENDING:
            raise BattleNotPendingError("This battle has already started.")
        if mine.slot != 2:
            raise NotInvitedError("You aren't the invited player in this battle.")

        challenge = await self._battles.challenge_for(locked)
        ensure_challenge_transition(
            ChallengeState(challenge.status.value), ChallengeState.CANCELLED
        )
        challenge.status = ChallengeStatus.CANCELLED

        mine.status = BattleParticipantStatus.DECLINED
        locked.status = BattleStatus.CANCELLED

        await self._session.flush()
        await self._publish(battle_channel(battle_id), "battle_status_changed", locked)
        await self._publish(group_channel(locked.group_id), "battle_status_changed", locked)
        return locked

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    async def submit_evidence(
        self,
        *,
        battle: Battle,
        user_id: uuid.UUID,
        provider_name: str,
        evidence: HealthEvidence,
        raw_payload: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> tuple[VerificationOutcome, BattleView]:
        """Submit today's evidence for the caller's own side of the battle.

        This adds no verification logic whatsoever: it locates the caller's
        `ChallengeParticipant` and hands the whole thing to `VerificationService`, the
        same call `POST /challenges/{id}/verify` makes. The provider registry, the
        challenge-day window, the target comparison and the XP award are all identical —
        which is exactly what §6 and §20 require.

        A caller can only ever submit for themselves: the participant row is looked up
        from the authenticated user, never from the request body.
        """
        now = now or datetime.now(UTC)
        if battle.status is not BattleStatus.ACTIVE:
            raise BattleNotActiveError(
                f"This battle is '{battle.status.value}' and accepts no evidence."
            )
        challenge = await self._battles.challenge_for(battle)
        participant = await self._participants.get(challenge.id, user_id)
        if participant is None:  # pragma: no cover - guarded by get_for_participant
            raise NotABattleParticipantError("You aren't in this battle.")

        outcome = await self._verification.submit(
            challenge=challenge,
            participant=participant,
            provider_name=provider_name,
            evidence=evidence,
            raw_payload=raw_payload,
            now=now,
        )

        # `view` sweeps and finalizes if this submission settled the battle, so the
        # status it reports is the one the client will see on its next read.
        view = await self.view(battle, user_id, now=now)
        if view.battle.status is not BattleStatus.COMPLETED:
            # Progress only — the payload carries no numbers, so a socket can never
            # become a side channel for the opponent's private record (§18). Clients
            # re-read REST, which is authoritative.
            await self._publish(battle_channel(battle.id), "battle_progress", battle)
        return outcome, view

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    async def finalize_if_due(
        self, battle: Battle, *, now: datetime | None = None
    ) -> bool:
        challenge = await self._battles.challenge_for(battle)
        return await self._finalize_if_due(battle, challenge, now=now or datetime.now(UTC))

    async def _finalize_if_due(
        self, battle: Battle, challenge: Challenge, *, now: datetime
    ) -> bool:
        """Decide the battle, once, in one transaction (§21).

        Due when either the battle's window has closed, or every day of the battle is
        already resolved for both players — at that point no further evidence can change
        a score, so waiting for the clock would only delay an outcome that is already
        determined. Both paths compute the same thing.

        The whole decision is a single locked, transactional step: resolve outstanding
        days → rank through the frozen tie-break → write outcomes → mirror onto the
        battle → award the win bonus → close the battle. It either all lands or none of
        it does, and a second attempt finds `status != ACTIVE` and does nothing.
        """
        locked = await self._battles.lock(battle.id)
        if locked is None or locked.status is not BattleStatus.ACTIVE:
            return False

        # Any day whose deadline has passed becomes a miss before anything is compared.
        await self._game.resolve_overdue_days(challenge, now=now)

        participants = await self._game_repo.all_participants(challenge.id)
        if len(participants) < 2:  # pragma: no cover - accept() creates the second
            return False

        if now < locked.end_at and not await self._all_days_resolved(
            challenge, participants
        ):
            return False

        # ---- The verdict. `points_outcomes` is the frozen §20.3 comparison: highest
        # score, then earliest to reach it, then longer streak, then earlier join, then
        # lower user id. Shared verbatim with POINTS-mode challenge close and with
        # leaderboard ordering, so a battle's winner can never disagree with its rank.
        standings = await self._game.standings(challenge, participants)
        outcomes = points_outcomes(standings)
        for participant in participants:
            if participant.outcome is None:
                participant.outcome = ParticipantOutcome(outcomes[participant.id].value)
            if participant.status is ParticipantStatus.ACTIVE:
                ensure_participant_transition(
                    ParticipantStateMachine.ACTIVE, ParticipantStateMachine.COMPLETED
                )
                participant.status = ParticipantStatus.COMPLETED

        ensure_challenge_transition(
            ChallengeState(challenge.status.value), ChallengeState.COMPLETED
        )
        challenge.status = ChallengeStatus.COMPLETED

        # ---- Mirror onto the battle (§20.3: the outcome is written to both).
        by_user = {p.user_id: p for p in participants}
        winner_id: uuid.UUID | None = None
        for side in await self._battles.participants(locked.id):
            challenge_participant = by_user[side.user_id]
            side.score = Decimal(challenge_participant.current_score)
            won = challenge_participant.outcome is ParticipantOutcome.WON
            side.status = (
                BattleParticipantStatus.WON if won else BattleParticipantStatus.LOST
            )
            if won:
                winner_id = side.user_id

        if winner_id is not None:
            await self._game.award_battle_win_xp(user_id=winner_id, battle_id=locked.id)

        locked.status = BattleStatus.COMPLETED
        locked.completed_at = now
        await self._session.flush()

        await self._publish(
            battle_channel(locked.id),
            "battle_completed",
            locked,
            extra={"winner_user_id": str(winner_id) if winner_id else None},
        )
        await self._publish(
            group_channel(locked.group_id),
            "battle_completed",
            locked,
            extra={"winner_user_id": str(winner_id) if winner_id else None},
        )
        return True

    async def _all_days_resolved(
        self, challenge: Challenge, participants: list[ChallengeParticipant]
    ) -> bool:
        """True when neither player has an open day left.

        A day is open only while it is PENDING; once it is COMPLETED or MISSED its
        contribution to the score is fixed. When both players have `duration_days`
        resolved days, the final scores are already known.
        """
        counts = await self._battles.resolved_day_counts(challenge.id)
        return all(
            counts.get(participant.id, 0) >= challenge.duration_days
            for participant in participants
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def view(
        self, battle: Battle, viewer_id: uuid.UUID, *, now: datetime | None = None
    ) -> BattleView:
        """Everything the battle screen renders, and nothing more.

        Reads sweep first (`finalize_if_due`), the same lazy-resolution pattern the
        leaderboard uses: a battle whose window closed hours ago must not still read as
        "live" merely because nobody has posted evidence since.
        """
        now = now or datetime.now(UTC)
        challenge = await self._battles.challenge_for(battle)
        if battle.status is BattleStatus.ACTIVE:
            await self._finalize_if_due(battle, challenge, now=now)

        rows = await self._battles.participants_with_names(battle.id)
        completed = await self._battles.completed_day_counts(challenge.id)
        challenge_participants = {
            p.user_id: p for p in await self._game_repo.all_participants(challenge.id)
        }

        sides: list[BattleSide] = []
        winner_user_id: uuid.UUID | None = None
        for side, display_name in rows:
            challenge_participant = challenge_participants.get(side.user_id)
            # Live score comes from the authoritative participant row; the battle's own
            # `score` column is the snapshot taken at finalization.
            score = (
                Decimal(challenge_participant.current_score)
                if challenge_participant is not None
                else Decimal(side.score)
            )
            if side.status is BattleParticipantStatus.WON:
                winner_user_id = side.user_id
            sides.append(
                BattleSide(
                    user_id=side.user_id,
                    display_name=display_name,
                    status=side.status,
                    score=score,
                    days_completed=(
                        completed.get(challenge_participant.id, 0)
                        if challenge_participant is not None
                        else 0
                    ),
                    is_me=side.user_id == viewer_id,
                )
            )

        my_outcome: Outcome | None = None
        mine = challenge_participants.get(viewer_id)
        if mine is not None and mine.outcome is not None:
            my_outcome = Outcome(mine.outcome.value)

        return BattleView(
            battle=battle,
            challenge=challenge,
            sides=sides,
            day_index=self._day_index(battle, challenge, now),
            my_outcome=my_outcome,
            winner_user_id=winner_user_id,
            my_xp_awarded=(
                await self._battles.win_bonus_awarded(viewer_id, battle.id)
                if my_outcome is Outcome.WON
                else None
            ),
        )

    def _day_index(self, battle: Battle, challenge: Challenge, now: datetime) -> int:
        """1-based "DAY 2 / 7", clamped. A pending battle is always day 1 — it hasn't
        started, so counting elapsed days would be counting nothing."""
        if battle.status is BattleStatus.PENDING:
            return 1
        start_day = resolve_challenge_day(battle.start_at, battle.timezone)
        today = resolve_challenge_day(now, battle.timezone)
        return max(1, min((today - start_day).days + 1, challenge.duration_days))

    async def list_for_user(
        self, user_id: uuid.UUID, *, status: BattleStatus | None = None
    ) -> list[BattleView]:
        """The Battles tab and battle history, in one authoritative list."""
        now = datetime.now(UTC)
        views: list[BattleView] = []
        for battle in await self._battles.list_for_user(user_id, status=status):
            views.append(await self.view(battle, user_id, now=now))
        return views

    async def rivals(
        self, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, str, int, int, uuid.UUID | None]]:
        """Squad-mates the caller can challenge, with the head-to-head record.

        `live_battle_id` (last element) is what stops the UI offering "CHALLENGE" to
        someone a battle is already running against — the server answers it rather than
        the client inferring it from a list it may not have.
        """
        records = await self._battles.head_to_head(user_id)
        live = await self._battles.live_opponents(user_id)
        return [
            (
                rival_id,
                display_name,
                records.get(rival_id, (0, 0))[0],
                records.get(rival_id, (0, 0))[1],
                live.get(rival_id),
            )
            for rival_id, display_name in await self._battles.group_rivals(group_id, user_id)
        ]

    def rank_positions(self, view: BattleView) -> dict[uuid.UUID, int]:
        """Presentation-only ordering of the two sides by score, highest first."""
        ordered = sorted(view.sides, key=lambda side: -side.score)
        return {side.user_id: index for index, side in enumerate(ordered, start=1)}

    # ------------------------------------------------------------------

    async def _publish(
        self,
        channel: str,
        event_type: str,
        battle: Battle,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Persist first, publish second (§14). Never raises — losing Redis costs live
        delivery and nothing durable, and the client reconciles over REST."""
        payload: dict[str, Any] = {
            "type": event_type,
            "battle_id": str(battle.id),
            "group_id": str(battle.group_id),
            "status": battle.status.value,
        }
        payload.update(extra or {})
        await publish_realtime(channel, payload)


__all__ = ["BattleService", "BattleSide", "BattleView"]
