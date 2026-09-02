"""XP awards and levels.

**These numbers were not frozen by Phase 0.** The architecture fixes the *shape* — XP is
strictly additive with no penalty for a miss (§20.2 / ADR 0002), an award is "completion
+ streak bonus" (design spec §9), and a level is a "linear, per-level threshold" — but
never the amounts. They are set here as service-layer constants following the precedent
ADR 0004 set for the failure rule: fixed in V1, with `ChallengeRule` as the extension
point if they ever need to vary per challenge. See ADR 0008 for the reasoning.

Pure Python — no framework imports (Architecture §2).
"""

# Flat award for completing a day. The bulk of the economy: showing up is the behaviour
# V1 wants to reward, and a flat number keeps "what did I earn?" answerable at a glance.
DAILY_COMPLETION_XP = 50

# Streak bonus, paid per consecutive day *beyond the first*, so day 1 earns the base
# award alone and the bonus grows as the habit holds.
STREAK_BONUS_PER_DAY = 10

# The bonus stops growing after this many days. Uncapped, a long streak would dwarf every
# other source and make a mid-challenge joiner unable to catch up no matter what they do.
MAX_STREAK_BONUS_DAYS = 5

# Linear threshold, per the design spec's "linear, per-level threshold" XP bar. Level 1
# starts at 0 XP.
XP_PER_LEVEL = 500


def completion_xp() -> int:
    return DAILY_COMPLETION_XP


def streak_bonus_xp(streak_after_completion: int) -> int:
    """Bonus for a day that brought the streak to `streak_after_completion`.

    Day 1 of a streak earns no bonus — the base award already covers showing up.
    """
    bonus_days = min(max(streak_after_completion - 1, 0), MAX_STREAK_BONUS_DAYS)
    return bonus_days * STREAK_BONUS_PER_DAY


def level_for_xp(xp_total: int) -> int:
    """1-based level. Negative totals are impossible in V1 but clamp rather than crash."""
    if xp_total < 0:
        return 1
    return xp_total // XP_PER_LEVEL + 1


def xp_into_level(xp_total: int) -> int:
    """XP earned inside the current level — the filled part of the progress bar."""
    if xp_total < 0:
        return 0
    return xp_total % XP_PER_LEVEL


def xp_to_next_level(xp_total: int) -> int:
    """XP still needed to reach the next level."""
    return XP_PER_LEVEL - xp_into_level(xp_total)
