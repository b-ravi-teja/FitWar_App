"""The V1 failure rule: miss 1 day → WARNING, miss 2 consecutive days → ELIMINATED.

Fixed constants, not `ChallengeRule` rows (ADR 0004) — making this configurable later
means reading these numbers from a rule row instead, which is not a schema change.

Applies to SURVIVAL only. POINTS challenges run their full duration and resolve by
final score; `applies_to` is what keeps that asymmetry in one place instead of scattered
`if mode == SURVIVAL` checks across the service layer.

Phase 3 scope: the rule is expressed and tested here, but nothing *evaluates* it against
real progress yet — daily progress stays PENDING until verification exists (Phase 4),
and warning/elimination processing is Phase 6.
"""

import enum

WARNING_THRESHOLD = 1
ELIMINATION_THRESHOLD = 2


class Mode(enum.StrEnum):
    SURVIVAL = "survival"
    POINTS = "points"


class FailureOutcome(enum.StrEnum):
    NONE = "none"
    WARNING = "warning"
    ELIMINATED = "eliminated"


def applies_to(mode: Mode) -> bool:
    return mode is Mode.SURVIVAL


def evaluate(mode: Mode, consecutive_misses: int) -> FailureOutcome:
    """What the given consecutive-miss count means for a participant in `mode`.

    "Consecutive" is the whole rule: completing a day resets the counter, so a warning
    never persists across an intervening completed day — matching the design's copy
    ("Complete today's mission to reset. Nobody's out yet.").
    """
    if not applies_to(mode):
        return FailureOutcome.NONE
    if consecutive_misses >= ELIMINATION_THRESHOLD:
        return FailureOutcome.ELIMINATED
    if consecutive_misses >= WARNING_THRESHOLD:
        return FailureOutcome.WARNING
    return FailureOutcome.NONE


def describe(mode: Mode) -> str:
    """The failure-rule line the Challenge Detail header renders."""
    if applies_to(mode):
        return "MISS TWICE → ELIMINATED"
    return "NO ELIMINATION · HIGHEST TOTAL WINS"
