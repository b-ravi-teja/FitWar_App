"""AppleHealthProvider verdict mapping — pure, no DB, no HealthKit."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.domain.verification.evidence import HealthEvidence
from app.domain.verification.metrics import ActivityKind
from app.domain.verification.result import VerificationContext, VerificationStatus
from app.integrations.verification_providers.apple_health import AppleHealthProvider

DAY_START = datetime(2026, 3, 10, 18, 30, tzinfo=UTC)
DAY_END = datetime(2026, 3, 11, 18, 30, tzinfo=UTC)
NOW = DAY_END - timedelta(hours=1)


def context(
    activity: ActivityKind = ActivityKind.STEPS, target: str = "10000"
) -> VerificationContext:
    return VerificationContext(
        activity=activity,
        target_value=Decimal(target),
        challenge_day=DAY_END.date(),
        day_start_at=DAY_START,
        day_end_at=DAY_END,
        now=NOW,
    )


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


provider = AppleHealthProvider()


class TestVerdict:
    def test_meeting_the_target_verifies(self) -> None:
        result = provider.evaluate(context=context(), evidence=evidence())
        assert result.verified
        assert result.status is VerificationStatus.VERIFIED
        assert result.reason_code is None
        assert result.value == Decimal("10500")
        assert result.target == Decimal("10000")

    def test_exactly_hitting_the_target_verifies(self) -> None:
        """The target is inclusive — 10,000 of 10,000 steps is a completed day."""
        result = provider.evaluate(context=context(), evidence=evidence(value=Decimal("10000")))
        assert result.verified

    def test_falling_short_is_inconclusive_not_rejected(self) -> None:
        """The measurement is trusted; it just hasn't reached the target yet, so the
        day stays open for a later sync rather than being marked a failure."""
        result = provider.evaluate(context=context(), evidence=evidence(value=Decimal("4000")))
        assert not result.verified
        assert result.status is VerificationStatus.INCONCLUSIVE
        assert result.reason_code == "TARGET_NOT_MET"

    def test_hand_entered_data_never_verifies(self) -> None:
        """A user can type 50,000 steps into Health; §8 requires a trusted source."""
        result = provider.evaluate(
            context=context(), evidence=evidence(value=Decimal("50000"), was_user_entered=True)
        )
        assert not result.verified
        assert result.status is VerificationStatus.INCONCLUSIVE
        assert result.reason_code == "USER_ENTERED_DATA"

    def test_malformed_evidence_is_rejected_with_its_reason(self) -> None:
        result = provider.evaluate(context=context(), evidence=evidence(unit="furlongs"))
        assert result.status is VerificationStatus.REJECTED
        assert result.reason_code == "UNSUPPORTED_UNIT"
        assert not result.verified


class TestConversionBeforeComparison:
    def test_distance_is_converted_before_being_compared(self) -> None:
        """5000 m against a 5 km target passes; comparing raw numbers would read it as
        5000 km and pass for the wrong reason, or fail if the target were larger."""
        result = provider.evaluate(
            context=context(ActivityKind.DISTANCE, target="5"),
            evidence=evidence(
                metric=ActivityKind.DISTANCE, value=Decimal("5000"), unit="m"
            ),
        )
        assert result.verified
        assert result.value == Decimal("5.000")

    def test_short_distance_in_metres_does_not_pass(self) -> None:
        result = provider.evaluate(
            context=context(ActivityKind.DISTANCE, target="5"),
            evidence=evidence(metric=ActivityKind.DISTANCE, value=Decimal("900"), unit="m"),
        )
        assert not result.verified
        assert result.reason_code == "TARGET_NOT_MET"


class TestRecordedFacts:
    def test_source_and_metric_identify_the_provider_and_quantity(self) -> None:
        result = provider.evaluate(
            context=context(ActivityKind.DISTANCE, target="5"),
            evidence=evidence(metric=ActivityKind.DISTANCE, value=Decimal("6"), unit="km"),
        )
        assert result.source == "apple_health"
        # Unit folded into the name — VerificationRecord has no unit column.
        assert result.metric == "distance_km"

    def test_source_timestamp_is_when_the_activity_happened(self) -> None:
        result = provider.evaluate(context=context(), evidence=evidence())
        assert result.source_timestamp == NOW
