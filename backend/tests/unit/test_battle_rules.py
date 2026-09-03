"""Battle configuration rules, and the tie-break they hand off to.

The tie-break itself is *not* reimplemented for battles — it is the frozen §20.3
`rank_key`, exercised here at each of its five levels with two competitors to prove a
battle's winner is decided by the same function a leaderboard sorts with.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.battles.exceptions import InvalidBattleConfigError
from app.domain.battles.rules import (
    MAX_DURATION_DAYS,
    default_target,
    validate_activity,
    validate_duration,
    validate_target,
)
from app.domain.game.standings import (
    Outcome,
    ParticipantState,
    Standing,
    points_outcomes,
)
from app.domain.game.xp_rules import battle_win_xp
from app.domain.verification.metrics import ActivityKind
from app.models.battle import pair_key

NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)


def _standing(
    *,
    score: str = "100",
    reached: datetime | None = NOW,
    streak: int = 3,
    joined: datetime = NOW,
    user_id: uuid.UUID | None = None,
) -> Standing:
    return Standing(
        participant_id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        score=Decimal(score),
        reached_score_at=reached,
        current_streak=streak,
        joined_at=joined,
        state=ParticipantState.ACTIVE,
    )


class TestConfiguration:
    def test_a_battle_needs_an_activity_health_can_measure(self) -> None:
        """Push-ups have no HealthKit type, and a two-player contest has no impartial
        reviewer for video proof — so it is refused rather than silently unverifiable."""
        with pytest.raises(InvalidBattleConfigError):
            validate_activity(ActivityKind.PUSHUPS)

    @pytest.mark.parametrize(
        "activity",
        [ActivityKind.STEPS, ActivityKind.ACTIVE_CALORIES, ActivityKind.DISTANCE],
    )
    def test_health_readable_activities_are_accepted(self, activity: ActivityKind) -> None:
        validate_activity(activity)
        assert default_target(activity) > 0

    def test_an_unmeasurable_activity_has_no_default_target(self) -> None:
        with pytest.raises(InvalidBattleConfigError):
            default_target(ActivityKind.PUSHUPS)

    @pytest.mark.parametrize("days", [0, -1, MAX_DURATION_DAYS + 1])
    def test_duration_is_bounded(self, days: int) -> None:
        with pytest.raises(InvalidBattleConfigError):
            validate_duration(days)

    def test_a_one_day_battle_is_legal(self) -> None:
        validate_duration(1)

    @pytest.mark.parametrize("target", ["0", "-1"])
    def test_a_target_must_be_positive(self, target: str) -> None:
        with pytest.raises(InvalidBattleConfigError):
            validate_target(Decimal(target))


class TestPairKey:
    def test_it_is_symmetric(self) -> None:
        """Which direction the invitation went must not create a second live battle."""
        a, b = uuid.uuid4(), uuid.uuid4()
        assert pair_key(a, b) == pair_key(b, a)

    def test_different_pairs_differ(self) -> None:
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        assert pair_key(a, b) != pair_key(a, c)


class TestTieBreak:
    """Each of the five frozen §20.3 levels, with exactly two competitors."""

    def test_level_1_higher_score_wins(self) -> None:
        winner = _standing(score="200")
        loser = _standing(score="100")

        outcomes = points_outcomes([loser, winner])

        assert outcomes[winner.participant_id] is Outcome.WON
        assert outcomes[loser.participant_id] is Outcome.LOST

    def test_level_2_tied_score_goes_to_whoever_reached_it_first(self) -> None:
        winner = _standing(reached=NOW)
        loser = _standing(reached=NOW + timedelta(minutes=1))

        outcomes = points_outcomes([loser, winner])

        assert outcomes[winner.participant_id] is Outcome.WON

    def test_level_3_same_score_and_time_goes_to_the_longer_streak(self) -> None:
        winner = _standing(streak=5)
        loser = _standing(streak=2)

        outcomes = points_outcomes([loser, winner])

        assert outcomes[winner.participant_id] is Outcome.WON

    def test_level_4_falls_through_to_who_joined_earlier(self) -> None:
        """In a battle this is always the challenger — they entered when they invited."""
        winner = _standing(joined=NOW - timedelta(hours=1))
        loser = _standing(joined=NOW)

        outcomes = points_outcomes([loser, winner])

        assert outcomes[winner.participant_id] is Outcome.WON

    def test_level_5_lower_user_id_is_the_final_fallback(self) -> None:
        low = uuid.UUID(int=1)
        high = uuid.UUID(int=2)
        winner = _standing(user_id=low)
        loser = _standing(user_id=high)

        outcomes = points_outcomes([loser, winner])

        assert outcomes[winner.participant_id] is Outcome.WON

    def test_it_is_deterministic_regardless_of_input_order(self) -> None:
        """Two identical database states must produce the same winner (§7)."""
        a = _standing(user_id=uuid.UUID(int=1))
        b = _standing(user_id=uuid.UUID(int=2))

        assert points_outcomes([a, b]) == points_outcomes([b, a])

    def test_exactly_one_side_wins(self) -> None:
        a = _standing(score="10")
        b = _standing(score="10")

        outcomes = points_outcomes([a, b])

        assert sorted(o.value for o in outcomes.values()) == ["lost", "won"]

    def test_a_battle_never_ends_in_a_draw(self) -> None:
        """Every level can tie; the fifth cannot, because user ids are distinct."""
        for _ in range(50):
            a = _standing(user_id=uuid.uuid4())
            b = _standing(user_id=uuid.uuid4())
            values = list(points_outcomes([a, b]).values())
            assert values.count(Outcome.WON) == 1


class TestXP:
    def test_the_win_bonus_is_a_fixed_positive_amount(self) -> None:
        assert battle_win_xp() > 0
