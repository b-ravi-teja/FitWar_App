"""State machine, failure rule, and invite-code generation — pure domain, no DB."""

import pytest

from app.domain.challenges.failure_rule import (
    ELIMINATION_THRESHOLD,
    WARNING_THRESHOLD,
    FailureOutcome,
    Mode,
    applies_to,
    describe,
    evaluate,
)
from app.domain.challenges.state_machine import (
    ChallengeState,
    InvalidTransitionError,
    ParticipantState,
    can_transition_challenge,
    can_transition_participant,
    ensure_challenge_transition,
    ensure_participant_transition,
    is_terminal_challenge_state,
    is_terminal_participant_state,
)
from app.domain.groups.join_code import ALPHABET, generate_join_code, normalize_join_code


class TestChallengeStateMachine:
    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (ChallengeState.DRAFT, ChallengeState.ACTIVE),
            (ChallengeState.DRAFT, ChallengeState.CANCELLED),
            (ChallengeState.ACTIVE, ChallengeState.COMPLETED),
        ],
    )
    def test_allows_exactly_the_documented_edges(
        self, current: ChallengeState, target: ChallengeState
    ) -> None:
        assert can_transition_challenge(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            # An in-flight challenge is never cancellable — participants already have
            # real daily progress against it.
            (ChallengeState.ACTIVE, ChallengeState.CANCELLED),
            (ChallengeState.ACTIVE, ChallengeState.DRAFT),
            (ChallengeState.DRAFT, ChallengeState.COMPLETED),
            (ChallengeState.COMPLETED, ChallengeState.ACTIVE),
            (ChallengeState.CANCELLED, ChallengeState.ACTIVE),
            (ChallengeState.COMPLETED, ChallengeState.CANCELLED),
        ],
    )
    def test_refuses_everything_else(
        self, current: ChallengeState, target: ChallengeState
    ) -> None:
        assert not can_transition_challenge(current, target)
        with pytest.raises(InvalidTransitionError):
            ensure_challenge_transition(current, target)

    def test_terminal_states(self) -> None:
        assert is_terminal_challenge_state(ChallengeState.COMPLETED)
        assert is_terminal_challenge_state(ChallengeState.CANCELLED)
        assert not is_terminal_challenge_state(ChallengeState.DRAFT)
        assert not is_terminal_challenge_state(ChallengeState.ACTIVE)

    def test_transition_error_is_a_conflict_with_a_stable_code(self) -> None:
        with pytest.raises(InvalidTransitionError) as exc:
            ensure_challenge_transition(ChallengeState.COMPLETED, ChallengeState.ACTIVE)
        assert exc.value.code == "INVALID_STATE_TRANSITION"


class TestParticipantStateMachine:
    @pytest.mark.parametrize(
        "target",
        [ParticipantState.COMPLETED, ParticipantState.LEFT, ParticipantState.ELIMINATED],
    )
    def test_active_can_reach_every_terminal_state(self, target: ParticipantState) -> None:
        assert can_transition_participant(ParticipantState.ACTIVE, target)

    @pytest.mark.parametrize(
        "current",
        [ParticipantState.COMPLETED, ParticipantState.LEFT, ParticipantState.ELIMINATED],
    )
    def test_terminal_states_never_revive(self, current: ParticipantState) -> None:
        assert is_terminal_participant_state(current)
        with pytest.raises(InvalidTransitionError):
            ensure_participant_transition(current, ParticipantState.ACTIVE)


class TestFailureRule:
    def test_thresholds_match_the_frozen_decision(self) -> None:
        assert (WARNING_THRESHOLD, ELIMINATION_THRESHOLD) == (1, 2)

    def test_applies_only_to_survival(self) -> None:
        assert applies_to(Mode.SURVIVAL)
        assert not applies_to(Mode.POINTS)

    @pytest.mark.parametrize(
        ("misses", "expected"),
        [
            (0, FailureOutcome.NONE),
            (1, FailureOutcome.WARNING),
            (2, FailureOutcome.ELIMINATED),
            (5, FailureOutcome.ELIMINATED),
        ],
    )
    def test_survival_escalates_with_consecutive_misses(
        self, misses: int, expected: FailureOutcome
    ) -> None:
        assert evaluate(Mode.SURVIVAL, misses) is expected

    @pytest.mark.parametrize("misses", [0, 1, 2, 9])
    def test_points_mode_never_warns_or_eliminates(self, misses: int) -> None:
        # "Everyone keeps playing. Highest total at the end takes the crown." (ADR 0004)
        assert evaluate(Mode.POINTS, misses) is FailureOutcome.NONE

    def test_describe_differs_per_mode(self) -> None:
        assert "ELIMINATED" in describe(Mode.SURVIVAL)
        assert "ELIMINATED" not in describe(Mode.POINTS)


class TestJoinCode:
    def test_shape_matches_the_design(self) -> None:
        code = generate_join_code()
        assert len(code) == 6
        assert code[2] == "-"
        assert all(ch in ALPHABET for ch in code.replace("-", ""))

    def test_alphabet_excludes_transcription_traps(self) -> None:
        for ambiguous in "IO01":
            assert ambiguous not in ALPHABET

    def test_codes_are_not_all_identical(self) -> None:
        assert len({generate_join_code() for _ in range(50)}) > 1

    @pytest.mark.parametrize("typed", ["k7-xr9", "K7XR9", " k7 xr9 ", "K7-xr9"])
    def test_normalize_accepts_what_humans_type(self, typed: str) -> None:
        assert normalize_join_code(typed) == "K7-XR9"

    def test_normalize_leaves_wrong_length_input_alone(self) -> None:
        # A too-short code must not be silently reshaped into something that could
        # collide with a real one — it just fails to match any group.
        assert normalize_join_code("K7") == "K7"
