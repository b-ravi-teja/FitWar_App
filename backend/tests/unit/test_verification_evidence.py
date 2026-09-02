"""Evidence validation and unit conversion — pure domain, no DB, no HTTP."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.verification.evidence import (
    CLOCK_SKEW_TOLERANCE,
    EvidenceRejection,
    HealthEvidence,
    validate,
)
from app.domain.verification.metrics import (
    ActivityKind,
    is_health_readable,
    is_supported_unit,
    supported_units,
    to_canonical,
)

DAY_START = datetime(2026, 3, 10, 18, 30, tzinfo=UTC)  # 2026-03-11 00:00 Asia/Kolkata
DAY_END = datetime(2026, 3, 11, 18, 30, tzinfo=UTC)
NOW = DAY_END - timedelta(hours=1)


def evidence(**overrides: object) -> HealthEvidence:
    base: dict[str, object] = {
        "metric": ActivityKind.STEPS,
        "value": Decimal("10500"),
        "unit": "steps",
        "period_start": DAY_START,
        "period_end": NOW,
    }
    base.update(overrides)
    return HealthEvidence(**base)  # type: ignore[arg-type]


def check(ev: HealthEvidence, activity: ActivityKind = ActivityKind.STEPS):  # type: ignore[no-untyped-def]
    return validate(
        ev, activity=activity, day_start_at=DAY_START, day_end_at=DAY_END, now=NOW
    )


class TestWellFormedEvidence:
    def test_accepts_evidence_inside_the_challenge_day(self) -> None:
        assert check(evidence()) is None

    def test_accepts_a_zero_measurement(self) -> None:
        """Zero is a real reading — the user did nothing yet — not malformed input."""
        assert check(evidence(value=Decimal(0))) is None


class TestMetricAndUnitRejection:
    def test_rejects_a_metric_the_challenge_does_not_measure(self) -> None:
        ev = evidence(metric=ActivityKind.DISTANCE, unit="km")
        assert check(ev, activity=ActivityKind.STEPS) is EvidenceRejection.INCOMPATIBLE_METRIC

    def test_rejects_an_unsupported_unit(self) -> None:
        """Guessing at an unknown unit is how a wrong number becomes a passed challenge."""
        assert check(evidence(unit="furlongs")) is EvidenceRejection.UNSUPPORTED_UNIT

    def test_rejects_pushups_as_health_evidence(self) -> None:
        """HealthKit cannot count push-ups; such a challenge is manual-proof only."""
        ev = evidence(metric=ActivityKind.PUSHUPS, unit="reps")
        rejection = check(ev, activity=ActivityKind.PUSHUPS)
        assert rejection is EvidenceRejection.METRIC_NOT_HEALTH_READABLE

    def test_rejects_a_negative_measurement(self) -> None:
        assert check(evidence(value=Decimal(-1))) is EvidenceRejection.NEGATIVE_VALUE


class TestPeriodRejection:
    def test_rejects_a_period_from_another_day(self) -> None:
        """The core timezone protection: evidence for yesterday cannot pass as today."""
        ev = evidence(
            period_start=DAY_START - timedelta(days=1),
            period_end=DAY_END - timedelta(days=1),
        )
        assert check(ev) is EvidenceRejection.OUTSIDE_CHALLENGE_DAY

    def test_rejects_a_period_that_starts_before_the_day_opened(self) -> None:
        """Spilling backwards would let yesterday's activity top up today's total."""
        ev = evidence(period_start=DAY_START - timedelta(hours=3))
        assert check(ev) is EvidenceRejection.OUTSIDE_CHALLENGE_DAY

    def test_rejects_a_period_that_spills_past_the_deadline(self) -> None:
        """Submitted after the day closed, covering a span wider than the day itself.

        `now` is after the deadline here, so this is genuinely a window violation and
        not the future-period check firing first.
        """
        ev = evidence(period_end=DAY_END + timedelta(hours=2))
        rejection = validate(
            ev,
            activity=ActivityKind.STEPS,
            day_start_at=DAY_START,
            day_end_at=DAY_END,
            now=DAY_END + timedelta(hours=3),
        )
        assert rejection is EvidenceRejection.OUTSIDE_CHALLENGE_DAY

    def test_rejects_an_inverted_period(self) -> None:
        ev = evidence(period_start=NOW, period_end=DAY_START)
        assert check(ev) is EvidenceRejection.INVERTED_PERIOD

    def test_rejects_a_period_in_the_future(self) -> None:
        """A device with a wildly wrong clock must not pre-claim a later day."""
        ev = evidence(period_end=NOW + timedelta(hours=2))
        assert check(ev) is EvidenceRejection.PERIOD_IN_FUTURE

    def test_tolerates_ordinary_clock_skew(self) -> None:
        """An honest phone a minute fast is not an attacker."""
        ev = evidence(
            period_start=DAY_START - (CLOCK_SKEW_TOLERANCE / 2),
            period_end=NOW + (CLOCK_SKEW_TOLERANCE / 2),
        )
        assert check(ev) is None


class TestUnitConversion:
    @pytest.mark.parametrize(
        ("activity", "value", "unit", "expected"),
        [
            (ActivityKind.DISTANCE, Decimal("5000"), "m", Decimal("5.000")),
            (ActivityKind.DISTANCE, Decimal("5"), "km", Decimal("5")),
            (ActivityKind.DISTANCE, Decimal("1"), "mi", Decimal("1.609344")),
            (ActivityKind.STEPS, Decimal("10000"), "count", Decimal("10000")),
        ],
    )
    def test_converts_into_the_canonical_unit(
        self, activity: ActivityKind, value: Decimal, unit: str, expected: Decimal
    ) -> None:
        assert to_canonical(activity, value, unit) == expected

    def test_metres_are_not_scored_as_kilometres(self) -> None:
        """The bug this conversion exists to prevent: 5000 m is 5 km, not 5000 km."""
        assert to_canonical(ActivityKind.DISTANCE, Decimal("5000"), "m") == Decimal("5.000")

    def test_unit_matching_ignores_case_and_padding(self) -> None:
        assert is_supported_unit(ActivityKind.DISTANCE, "  KM ")
        assert to_canonical(ActivityKind.DISTANCE, Decimal("2"), " KM ") == Decimal("2")

    def test_health_readable_set_excludes_only_pushups(self) -> None:
        assert is_health_readable(ActivityKind.STEPS)
        assert is_health_readable(ActivityKind.ACTIVE_CALORIES)
        assert is_health_readable(ActivityKind.DISTANCE)
        assert not is_health_readable(ActivityKind.PUSHUPS)

    def test_every_activity_declares_its_units(self) -> None:
        for activity in ActivityKind:
            assert supported_units(activity), activity
