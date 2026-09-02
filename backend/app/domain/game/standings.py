"""Ranking and final outcomes — the frozen §20.3 rules, expressed once.

Both the live leaderboard and challenge-close outcome assignment sort through
`rank_key` here, which is what makes "rank" and "outcome" structurally incapable of
disagreeing about who is ahead.

Pure Python: takes plain values, so it can be exercised without a database.
"""

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal


class Mode(enum.StrEnum):
    SURVIVAL = "survival"
    POINTS = "points"


class ParticipantState(enum.StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    LEFT = "left"
    ELIMINATED = "eliminated"


class Outcome(enum.StrEnum):
    WON = "won"
    LOST = "lost"
    OUT = "out"
    LEFT = "left"


# Sorts after every real timestamp, for participants who have never completed a day.
# Timezone-aware deliberately: every stored timestamp is aware, and a naive sentinel
# raises TypeError the moment they're compared — which is day one of every challenge.
_NEVER = datetime.max.replace(tzinfo=UTC)


@dataclass(frozen=True)
class Standing:
    """One participant's comparable state. `reached_score_at` is when the day that
    produced their current tally completed — the second tie-break key."""

    participant_id: uuid.UUID
    user_id: uuid.UUID
    score: Decimal
    reached_score_at: datetime | None
    current_streak: int
    joined_at: datetime
    state: ParticipantState


def rank_key(standing: Standing) -> tuple[Decimal, datetime, int, datetime, uuid.UUID]:
    """The frozen 5-step tie-break (§20.3), as a sort key.

    Ordering is ascending, so every "higher wins" term is negated: highest score, then
    whoever reached it first, then longer streak, then earlier join, then lower user_id.
    The final term makes the order total — V1 never produces an unresolved draw.
    """
    return (
        -standing.score,
        standing.reached_score_at or _NEVER,
        -standing.current_streak,
        standing.joined_at,
        standing.user_id,
    )


def rank(standings: list[Standing]) -> list[tuple[int, Standing]]:
    """Standings in rank order, 1-based.

    Eliminated and departed participants are ranked alongside everyone else rather than
    hidden: the design's leaderboard shows them with their status, and dropping them
    would silently renumber the survivors above them.
    """
    return list(enumerate(sorted(standings, key=rank_key), start=1))


def survival_outcome(state: ParticipantState) -> Outcome:
    """SURVIVAL has no LOST: reaching the end without elimination is a win, and there can
    be many winners (§20.3 — it's a survival game, not a ranking game)."""
    if state is ParticipantState.ELIMINATED:
        return Outcome.OUT
    if state is ParticipantState.LEFT:
        return Outcome.LEFT
    return Outcome.WON


def points_outcomes(standings: list[Standing]) -> dict[uuid.UUID, Outcome]:
    """Exactly one WON among finishers; everyone else who finished LOST.

    Participants who left keep LEFT and are excluded from the contest — they didn't
    finish, so they can neither win it nor lose it.
    """
    outcomes: dict[uuid.UUID, Outcome] = {}
    finishers = []
    for standing in standings:
        if standing.state is ParticipantState.LEFT:
            outcomes[standing.participant_id] = Outcome.LEFT
        else:
            finishers.append(standing)

    for position, standing in enumerate(sorted(finishers, key=rank_key)):
        outcomes[standing.participant_id] = Outcome.WON if position == 0 else Outcome.LOST
    return outcomes
