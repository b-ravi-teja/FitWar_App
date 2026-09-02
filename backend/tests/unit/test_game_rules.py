"""XP, level and standings rules — pure domain, no DB."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.game import xp_rules
from app.domain.game.standings import (
    Outcome,
    ParticipantState,
    Standing,
    points_outcomes,
    rank,
    survival_outcome,
)

BASE = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def standing(
    *,
    score: str = "100",
    reached: datetime | None = BASE,
    streak: int = 0,
    joined: datetime = BASE,
    state: ParticipantState = ParticipantState.ACTIVE,
    user_id: uuid.UUID | None = None,
) -> Standing:
    return Standing(
        participant_id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        score=Decimal(score),
        reached_score_at=reached,
        current_streak=streak,
        joined_at=joined,
        state=state,
    )


class TestXPAwards:
    def test_completion_pays_the_flat_award(self) -> None:
        assert xp_rules.completion_xp() == xp_rules.DAILY_COMPLETION_XP

    def test_first_day_of_a_streak_earns_no_bonus(self) -> None:
        """The base award already covers showing up; the bonus rewards continuing."""
        assert xp_rules.streak_bonus_xp(1) == 0

    def test_bonus_grows_with_the_streak(self) -> None:
        assert xp_rules.streak_bonus_xp(2) == xp_rules.STREAK_BONUS_PER_DAY
        assert xp_rules.streak_bonus_xp(4) == 3 * xp_rules.STREAK_BONUS_PER_DAY

    def test_bonus_stops_growing_at_the_cap(self) -> None:
        """Uncapped, a long streak would make a late joiner mathematically unable to
        catch up regardless of effort."""
        capped = xp_rules.MAX_STREAK_BONUS_DAYS * xp_rules.STREAK_BONUS_PER_DAY
        assert xp_rules.streak_bonus_xp(50) == capped
        assert xp_rules.streak_bonus_xp(xp_rules.MAX_STREAK_BONUS_DAYS + 1) == capped

    def test_awards_are_never_negative(self) -> None:
        """V1's ledger is strictly additive (ADR 0002) — no miss ever debits."""
        assert xp_rules.completion_xp() >= 0
        for streak in range(0, 20):
            assert xp_rules.streak_bonus_xp(streak) >= 0


class TestLevels:
    def test_level_one_starts_at_zero(self) -> None:
        assert xp_rules.level_for_xp(0) == 1

    def test_levels_are_linear(self) -> None:
        per = xp_rules.XP_PER_LEVEL
        assert xp_rules.level_for_xp(per - 1) == 1
        assert xp_rules.level_for_xp(per) == 2
        assert xp_rules.level_for_xp(per * 5) == 6

    def test_progress_within_a_level_sums_to_the_threshold(self) -> None:
        for total in (0, 137, 499, 500, 1234):
            assert (
                xp_rules.xp_into_level(total) + xp_rules.xp_to_next_level(total)
                == xp_rules.XP_PER_LEVEL
            )

    def test_level_is_monotonic(self) -> None:
        """More XP never means a lower level."""
        levels = [xp_rules.level_for_xp(x) for x in range(0, 3000, 50)]
        assert levels == sorted(levels)


class TestRanking:
    def test_orders_by_score_descending(self) -> None:
        low, high = standing(score="10"), standing(score="90")
        assert [s for _, s in rank([low, high])] == [high, low]

    def test_ranks_are_one_based_and_dense(self) -> None:
        ranked = rank([standing(score="30"), standing(score="20"), standing(score="10")])
        assert [position for position, _ in ranked] == [1, 2, 3]

    def test_tie_breaks_on_who_reached_the_score_first(self) -> None:
        """§20.3 step 2."""
        earlier = standing(score="50", reached=BASE)
        later = standing(score="50", reached=BASE + timedelta(minutes=5))
        assert [s for _, s in rank([later, earlier])] == [earlier, later]

    def test_then_on_longer_streak(self) -> None:
        """§20.3 step 3 — same score, same instant."""
        longer = standing(score="50", streak=9)
        shorter = standing(score="50", streak=2)
        assert [s for _, s in rank([shorter, longer])] == [longer, shorter]

    def test_then_on_earlier_join(self) -> None:
        earlier = standing(score="50", joined=BASE)
        later = standing(score="50", joined=BASE + timedelta(days=1))
        assert [s for _, s in rank([later, earlier])] == [earlier, later]

    def test_finally_on_lower_user_id(self) -> None:
        """The stable last resort — V1 never returns an unresolved draw."""
        low = standing(score="50", user_id=uuid.UUID(int=1))
        high = standing(score="50", user_id=uuid.UUID(int=2))
        assert [s for _, s in rank([high, low])] == [low, high]

    def test_ranking_is_deterministic_across_input_orders(self) -> None:
        entries = [standing(score="50") for _ in range(5)] + [standing(score="80")]
        first = [s.participant_id for _, s in rank(list(entries))]
        second = [s.participant_id for _, s in rank(list(reversed(entries)))]
        assert first == second

    def test_a_participant_who_never_scored_ranks_last_among_equals(self) -> None:
        never = standing(score="0", reached=None)
        scored = standing(score="0", reached=BASE)
        assert [s for _, s in rank([never, scored])] == [scored, never]

    def test_eliminated_participants_still_appear(self) -> None:
        """Dropping them would silently renumber everyone above them."""
        out = standing(score="10", state=ParticipantState.ELIMINATED)
        alive = standing(score="5")
        ranked = rank([alive, out])
        assert {s.participant_id for _, s in ranked} == {out.participant_id, alive.participant_id}


class TestSurvivalOutcomes:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            (ParticipantState.ACTIVE, Outcome.WON),
            (ParticipantState.COMPLETED, Outcome.WON),
            (ParticipantState.ELIMINATED, Outcome.OUT),
            (ParticipantState.LEFT, Outcome.LEFT),
        ],
    )
    def test_outcome_per_state(self, state: ParticipantState, expected: Outcome) -> None:
        assert survival_outcome(state) is expected

    def test_survival_can_have_many_winners(self) -> None:
        """It's a survival game, not a ranking game (§20.3) — everyone still standing won."""
        survivors = [ParticipantState.ACTIVE, ParticipantState.COMPLETED]
        assert all(survival_outcome(s) is Outcome.WON for s in survivors)


class TestPointsOutcomes:
    def test_exactly_one_winner(self) -> None:
        entries = [standing(score="10"), standing(score="90"), standing(score="50")]
        outcomes = points_outcomes(entries)
        assert list(outcomes.values()).count(Outcome.WON) == 1

    def test_highest_score_wins_and_the_rest_lose(self) -> None:
        winner = standing(score="90")
        loser = standing(score="10")
        outcomes = points_outcomes([loser, winner])
        assert outcomes[winner.participant_id] is Outcome.WON
        assert outcomes[loser.participant_id] is Outcome.LOST

    def test_a_tie_is_broken_not_shared(self) -> None:
        earlier = standing(score="50", reached=BASE)
        later = standing(score="50", reached=BASE + timedelta(minutes=1))
        outcomes = points_outcomes([later, earlier])
        assert outcomes[earlier.participant_id] is Outcome.WON
        assert outcomes[later.participant_id] is Outcome.LOST

    def test_departed_participants_keep_left_and_cannot_win(self) -> None:
        """They didn't finish, so they can neither win the contest nor lose it."""
        gone = standing(score="999", state=ParticipantState.LEFT)
        finisher = standing(score="10")
        outcomes = points_outcomes([gone, finisher])
        assert outcomes[gone.participant_id] is Outcome.LEFT
        assert outcomes[finisher.participant_id] is Outcome.WON

    def test_a_lone_finisher_wins(self) -> None:
        alone = standing(score="1")
        assert points_outcomes([alone])[alone.participant_id] is Outcome.WON
