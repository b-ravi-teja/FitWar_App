"""Activity metrics and their units.

The single authority on what a challenge's `unit` string may be and how a submitted
value converts to it. Keeping conversion here — rather than trusting whatever unit the
client happens to send — is what stops "I did 5000 metres" being scored against a
5 km target as though it were 5000 km.

Pure Python: `ActivityKind` deliberately restates the values of `models.ActivityType`
rather than importing it, so the domain layer keeps zero SQLAlchemy imports
(Architecture §2), the same treatment `state_machine.py` gives the status enums.
"""

import enum
from decimal import Decimal


class ActivityKind(enum.StrEnum):
    STEPS = "steps"
    ACTIVE_CALORIES = "active_calories"
    DISTANCE = "distance"
    PUSHUPS = "pushups"


# The unit a challenge target is compared in, per activity.
CANONICAL_UNIT: dict[ActivityKind, str] = {
    ActivityKind.STEPS: "steps",
    ActivityKind.ACTIVE_CALORIES: "kcal",
    ActivityKind.DISTANCE: "km",
    ActivityKind.PUSHUPS: "reps",
}

# Stable metric identifier recorded on every VerificationRecord. The unit is folded in
# wherever it would otherwise be ambiguous, matching Architecture §8's own examples
# ("steps" | "duration_minutes" | "distance_km") — `VerificationRecord` has no separate
# unit column, so a bare "distance" would leave stored history unreadable.
METRIC_NAME: dict[ActivityKind, str] = {
    ActivityKind.STEPS: "steps",
    ActivityKind.ACTIVE_CALORIES: "active_calories_kcal",
    ActivityKind.DISTANCE: "distance_km",
    ActivityKind.PUSHUPS: "pushups_reps",
}

# Accepted submission units → multiplier into the canonical unit. Anything absent is
# rejected rather than guessed: silently coercing an unknown unit is how a wrong number
# becomes a passed challenge.
_CONVERSIONS: dict[ActivityKind, dict[str, Decimal]] = {
    ActivityKind.STEPS: {
        "steps": Decimal(1),
        "count": Decimal(1),
    },
    ActivityKind.ACTIVE_CALORIES: {
        "kcal": Decimal(1),
        "kj": Decimal("0.2390057361"),
    },
    ActivityKind.DISTANCE: {
        "km": Decimal(1),
        "m": Decimal("0.001"),
        "mi": Decimal("1.609344"),
    },
    ActivityKind.PUSHUPS: {
        "reps": Decimal(1),
        "count": Decimal(1),
    },
}

# What Apple Health can actually measure. PUSHUPS is absent on purpose — HealthKit has
# no push-up count, so a pushups challenge is a manual-proof challenge and an
# apple_health submission against one is a configuration error, not a failed attempt.
HEALTH_READABLE: frozenset[ActivityKind] = frozenset(
    {ActivityKind.STEPS, ActivityKind.ACTIVE_CALORIES, ActivityKind.DISTANCE}
)


def normalize_unit(raw: str) -> str:
    return raw.strip().lower()


def is_supported_unit(activity: ActivityKind, unit: str) -> bool:
    return normalize_unit(unit) in _CONVERSIONS[activity]


def supported_units(activity: ActivityKind) -> tuple[str, ...]:
    return tuple(_CONVERSIONS[activity])


def to_canonical(activity: ActivityKind, value: Decimal, unit: str) -> Decimal:
    """Convert `value` into the activity's canonical unit.

    Raises `KeyError` for an unsupported unit — callers validate first with
    `is_supported_unit` so the error surfaces as a typed domain rejection.
    """
    return value * _CONVERSIONS[activity][normalize_unit(unit)]


def is_health_readable(activity: ActivityKind) -> bool:
    return activity in HEALTH_READABLE
