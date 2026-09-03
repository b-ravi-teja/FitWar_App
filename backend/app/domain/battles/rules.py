"""1v1 battle rules that are genuinely battle-specific.

Everything a battle shares with a challenge — the daily target comparison, the failure
rule (which does not apply, §20.4), scoring, XP per completed day — lives in the
challenge/game domain and is *used* here, not restated. What remains is small:
the shape of a valid battle configuration, and which activities a battle can measure.

Pure Python. No framework, no ORM (Architecture §2).
"""

from decimal import Decimal

from app.domain.battles.exceptions import InvalidBattleConfigError
from app.domain.verification.metrics import ActivityKind, is_health_readable

# Same bounds a group challenge uses — a battle is a challenge with two players, and a
# second, different limit would be a rule nobody asked for.
MIN_DURATION_DAYS = 1
MAX_DURATION_DAYS = 365

# `POST /battles` makes `target_value` optional (API_SPEC), so the server needs its own
# defaults rather than trusting whatever the client would otherwise have to invent.
# These match the design's own per-activity defaults on the create flow. See ADR 0009.
DEFAULT_TARGET: dict[ActivityKind, Decimal] = {
    ActivityKind.STEPS: Decimal(10_000),
    ActivityKind.ACTIVE_CALORIES: Decimal(500),
    ActivityKind.DISTANCE: Decimal(5),
}


def default_target(activity: ActivityKind) -> Decimal:
    try:
        return DEFAULT_TARGET[activity]
    except KeyError as exc:
        raise InvalidBattleConfigError(
            f"'{activity.value}' can't be used for a battle."
        ) from exc


def validate_activity(activity: ActivityKind) -> None:
    """V1 battles verify automatically, so the activity has to be health-readable.

    Manual video proof needs a reviewer who isn't competing, and a two-player contest
    has none — the frozen reviewer set (§20.5: challenge creator + group admins) puts
    the battle's own creator in the chair. Rather than invent an impartial-reviewer
    rule the architecture doesn't define, V1 battles are restricted to activities
    Apple Health can measure. See ADR 0009.
    """
    if not is_health_readable(activity):
        raise InvalidBattleConfigError(
            f"'{activity.value}' can't be verified automatically, and battles have no "
            "impartial reviewer for video proof."
        )


def validate_duration(duration_days: int) -> None:
    if duration_days < MIN_DURATION_DAYS or duration_days > MAX_DURATION_DAYS:
        raise InvalidBattleConfigError(
            f"A battle runs for between {MIN_DURATION_DAYS} and {MAX_DURATION_DAYS} days."
        )


def validate_target(target_value: Decimal) -> None:
    if target_value <= 0:
        raise InvalidBattleConfigError("Daily target must be greater than zero.")
