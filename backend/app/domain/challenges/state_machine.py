"""Challenge and participant state machines (Architecture §3.3).

The allowed edges are declared as data and checked by one function each, so an invalid
transition is impossible to express rather than merely discouraged. Services call
`ensure_*` before writing; the client never names a target state directly.

Pure Python — these enums are string values matching the ORM enums, deliberately
redeclared here so the domain layer keeps zero SQLAlchemy imports (Architecture §2).
"""

import enum

from app.domain.common.exceptions import ConflictError


class ChallengeState(enum.StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ParticipantState(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    LEFT = "left"
    ELIMINATED = "eliminated"


class InvalidTransitionError(ConflictError):
    """A refused state change. A `DomainError` rather than a bare exception so an
    illegal transition surfaces as a 409 the client can act on, not a 500."""

    code = "INVALID_STATE_TRANSITION"

    def __init__(self, current: str, target: str) -> None:
        self.current = current
        self.target = target
        super().__init__(f"Cannot transition from '{current}' to '{target}'.")


# Exactly the edges in Architecture §3.3 — DRAFT→ACTIVE→COMPLETED and DRAFT→CANCELLED.
# An ACTIVE challenge is never cancellable: participants have already accrued real
# daily progress against it, and discarding that is not a state change but a deletion.
CHALLENGE_TRANSITIONS: dict[ChallengeState, frozenset[ChallengeState]] = {
    ChallengeState.DRAFT: frozenset({ChallengeState.ACTIVE, ChallengeState.CANCELLED}),
    ChallengeState.ACTIVE: frozenset({ChallengeState.COMPLETED}),
    ChallengeState.COMPLETED: frozenset(),
    ChallengeState.CANCELLED: frozenset(),
}

# ELIMINATED is only reachable in SURVIVAL mode (ADR 0004); the graph allows the edge,
# and `failure_rule.py` is what decides whether it may ever be taken for a given mode.
PARTICIPANT_TRANSITIONS: dict[ParticipantState, frozenset[ParticipantState]] = {
    ParticipantState.ACTIVE: frozenset(
        {ParticipantState.COMPLETED, ParticipantState.LEFT, ParticipantState.ELIMINATED}
    ),
    ParticipantState.COMPLETED: frozenset(),
    ParticipantState.LEFT: frozenset(),
    ParticipantState.ELIMINATED: frozenset(),
}


def can_transition_challenge(current: ChallengeState, target: ChallengeState) -> bool:
    return target in CHALLENGE_TRANSITIONS[current]


def ensure_challenge_transition(current: ChallengeState, target: ChallengeState) -> None:
    if not can_transition_challenge(current, target):
        raise InvalidTransitionError(current.value, target.value)


def can_transition_participant(current: ParticipantState, target: ParticipantState) -> bool:
    return target in PARTICIPANT_TRANSITIONS[current]


def ensure_participant_transition(current: ParticipantState, target: ParticipantState) -> None:
    if not can_transition_participant(current, target):
        raise InvalidTransitionError(current.value, target.value)


def is_terminal_challenge_state(state: ChallengeState) -> bool:
    return not CHALLENGE_TRANSITIONS[state]


def is_terminal_participant_state(state: ParticipantState) -> bool:
    return not PARTICIPANT_TRANSITIONS[state]
