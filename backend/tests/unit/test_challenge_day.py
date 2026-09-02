"""Timezone/day-boundary resolution — the piece Architecture §11 says must be built and
tested in isolation before anything depends on it.
"""

from datetime import UTC, date, datetime

import pytest

from app.domain.challenges.challenge_day import (
    InvalidTimezoneError,
    challenge_end_at,
    day_deadline_utc,
    day_index,
    day_start_utc,
    is_valid_timezone,
    is_within_challenge,
    resolve_challenge_day,
    resolve_timezone,
)


class TestTimezoneValidation:
    def test_accepts_iana_identifier(self) -> None:
        assert is_valid_timezone("Asia/Kolkata")
        assert resolve_timezone("America/New_York") is not None

    @pytest.mark.parametrize("value", ["UTC+5", "+05:30", "Mars/Olympus", "", "GMT+2"])
    def test_rejects_non_iana_values(self, value: str) -> None:
        # Fixed UTC offsets are explicitly not allowed (Architecture §11) — they can't
        # express DST, which is the whole reason IANA identifiers are required.
        assert not is_valid_timezone(value)

    def test_invalid_timezone_raises(self) -> None:
        with pytest.raises(InvalidTimezoneError):
            resolve_timezone("Not/AZone")


class TestResolveChallengeDay:
    def test_uses_challenge_timezone_not_utc(self) -> None:
        # 18:30 UTC is already the next calendar day in Kolkata (UTC+5:30).
        moment = datetime(2026, 3, 1, 18, 30, tzinfo=UTC)
        assert resolve_challenge_day(moment, "UTC") == date(2026, 3, 1)
        assert resolve_challenge_day(moment, "Asia/Kolkata") == date(2026, 3, 2)

    def test_west_of_utc_is_still_the_previous_day(self) -> None:
        moment = datetime(2026, 3, 2, 4, 0, tzinfo=UTC)
        assert resolve_challenge_day(moment, "America/Los_Angeles") == date(2026, 3, 1)


class TestDayBoundaries:
    def test_day_starts_at_local_midnight(self) -> None:
        start = day_start_utc(date(2026, 6, 1), "Asia/Kolkata")
        assert start == datetime(2026, 5, 31, 18, 30, tzinfo=UTC)

    def test_deadline_is_the_next_local_midnight(self) -> None:
        deadline = day_deadline_utc(date(2026, 6, 1), "Asia/Kolkata")
        assert deadline == datetime(2026, 6, 1, 18, 30, tzinfo=UTC)

    def test_spring_forward_day_is_23_hours(self) -> None:
        # US DST starts 2026-03-08. That challenge-day is genuinely 23 hours long, and
        # the deadline must reflect that rather than being a fixed +24h.
        day = date(2026, 3, 8)
        length = day_deadline_utc(day, "America/New_York") - day_start_utc(
            day, "America/New_York"
        )
        assert length.total_seconds() == 23 * 3600

    def test_fall_back_day_is_25_hours(self) -> None:
        day = date(2026, 11, 1)
        length = day_deadline_utc(day, "America/New_York") - day_start_utc(
            day, "America/New_York"
        )
        assert length.total_seconds() == 25 * 3600

    def test_non_dst_zone_is_always_24_hours(self) -> None:
        day = date(2026, 3, 8)
        length = day_deadline_utc(day, "Asia/Kolkata") - day_start_utc(day, "Asia/Kolkata")
        assert length.total_seconds() == 24 * 3600


class TestDayIndex:
    def test_first_day_is_one(self) -> None:
        assert day_index(date(2026, 6, 1), date(2026, 6, 1)) == 1

    def test_counts_forward(self) -> None:
        assert day_index(date(2026, 6, 6), date(2026, 6, 1)) == 6

    def test_within_challenge_range(self) -> None:
        start = date(2026, 6, 1)
        assert is_within_challenge(date(2026, 6, 1), start, 30)
        assert is_within_challenge(date(2026, 6, 30), start, 30)
        assert not is_within_challenge(date(2026, 7, 1), start, 30)
        assert not is_within_challenge(date(2026, 5, 31), start, 30)


class TestChallengeEnd:
    def test_ends_at_local_midnight_after_the_final_day(self) -> None:
        start = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)  # 14:30 in Kolkata, day 1
        end = challenge_end_at(start, "Asia/Kolkata", 30)
        # Day 30 is 2026-06-30; the challenge ends when that day ends.
        assert end == day_deadline_utc(date(2026, 6, 30), "Asia/Kolkata")

    def test_single_day_challenge_ends_the_same_day(self) -> None:
        start = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
        end = challenge_end_at(start, "UTC", 1)
        assert end == datetime(2026, 6, 2, 0, 0, tzinfo=UTC)

    def test_spanning_a_dst_change_still_ends_at_local_midnight(self) -> None:
        start = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        end = challenge_end_at(start, "America/New_York", 14)
        # Not start + 14*24h: the DST transition inside the window shortens one day.
        assert end == day_deadline_utc(date(2026, 3, 14), "America/New_York")
