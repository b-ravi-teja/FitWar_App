"""Challenge-day resolution — the single authority for what "today" means.

Architecture §11: a challenge's daily boundary is governed by the timezone snapshotted
onto it at creation, resolved server-side from UTC. Nothing here trusts a client-supplied
date, and nothing here uses a fixed UTC offset — IANA identifiers only, so DST produces
a correct 23- or 25-hour day rather than a special case.

Pure Python. No FastAPI, no SQLAlchemy — the whole point is that this is testable in
isolation before anything depends on it.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class InvalidTimezoneError(ValueError):
    """Raised for a string that isn't a resolvable IANA timezone identifier."""


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidTimezoneError(f"'{name}' is not a valid IANA timezone identifier.") from exc


def is_valid_timezone(name: str) -> bool:
    try:
        resolve_timezone(name)
    except InvalidTimezoneError:
        return False
    return True


def resolve_challenge_day(now_utc: datetime, timezone: str) -> date:
    """The challenge-day `now_utc` falls in, as seen from the challenge's timezone."""
    return now_utc.astimezone(resolve_timezone(timezone)).date()


def day_start_utc(challenge_day: date, timezone: str) -> datetime:
    """UTC instant at which `challenge_day` begins in the challenge's timezone."""
    tz = resolve_timezone(timezone)
    return datetime.combine(challenge_day, time.min, tzinfo=tz).astimezone(UTC)


def day_deadline_utc(challenge_day: date, timezone: str) -> datetime:
    """UTC instant at which `challenge_day` ends — i.e. local midnight the next day.

    Derived from the *next day's* start rather than by adding 24 hours, so a DST
    transition shortens or lengthens the day instead of silently shifting the boundary.
    """
    return day_start_utc(challenge_day + timedelta(days=1), timezone)


def day_index(challenge_day: date, start_day: date) -> int:
    """1-based day number, as the UI shows it ("DAY 6 / 30")."""
    return (challenge_day - start_day).days + 1


def is_within_challenge(challenge_day: date, start_day: date, duration_days: int) -> bool:
    index = day_index(challenge_day, start_day)
    return 1 <= index <= duration_days


def challenge_end_at(start_at_utc: datetime, timezone: str, duration_days: int) -> datetime:
    """End instant of a challenge: the deadline of its final challenge-day.

    Computed through the timezone rather than as `start + duration_days` so that a
    challenge spanning a DST change ends at local midnight, not an hour either side.
    """
    start_day = resolve_challenge_day(start_at_utc, timezone)
    final_day = start_day + timedelta(days=duration_days - 1)
    return day_deadline_utc(final_day, timezone)
