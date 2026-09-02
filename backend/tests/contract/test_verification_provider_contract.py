"""Shared contract suite for every VerificationProvider (Architecture §8).

Runs against each registered provider, so a new one that can't satisfy the interface
fails here rather than surfacing as a runtime bug inside challenge logic. Parametrized
over the registry itself — adding Health Connect or Garmin later automatically brings
it under these tests with no edit to this file.
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.domain.verification.evidence import HealthEvidence
from app.domain.verification.metrics import ActivityKind
from app.domain.verification.result import (
    VerificationContext,
    VerificationResult,
    VerificationStatus,
)
from app.integrations.verification_providers.registry import (
    get_provider,
    supported_methods,
)

DAY_START = datetime(2026, 3, 10, 18, 30, tzinfo=UTC)
DAY_END = datetime(2026, 3, 11, 18, 30, tzinfo=UTC)
NOW = DAY_END - timedelta(hours=1)

CONTEXT = VerificationContext(
    activity=ActivityKind.STEPS,
    target_value=Decimal("10000"),
    challenge_day=DAY_END.date(),
    day_start_at=DAY_START,
    day_end_at=DAY_END,
    now=NOW,
)

PASSING = HealthEvidence(
    metric=ActivityKind.STEPS,
    value=Decimal("12000"),
    unit="steps",
    period_start=DAY_START,
    period_end=NOW,
)

MALFORMED = HealthEvidence(
    metric=ActivityKind.STEPS,
    value=Decimal("12000"),
    unit="furlongs",
    period_start=DAY_START,
    period_end=NOW,
)


@pytest.fixture(params=supported_methods())
def provider(request: pytest.FixtureRequest):  # type: ignore[no-untyped-def]
    return get_provider(request.param)


class TestProviderContract:
    def test_declares_a_source_identifier(self, provider) -> None:  # type: ignore[no-untyped-def]
        assert isinstance(provider.source, str) and provider.source

    def test_returns_a_verification_result(self, provider) -> None:  # type: ignore[no-untyped-def]
        result = provider.evaluate(context=CONTEXT, evidence=PASSING)
        assert isinstance(result, VerificationResult)

    def test_result_is_internally_consistent(self, provider) -> None:  # type: ignore[no-untyped-def]
        """`verified` must agree with `status` — a provider cannot report a pass with a
        non-VERIFIED status, or vice versa. Challenge logic branches on both."""
        for evidence in (PASSING, MALFORMED):
            result = provider.evaluate(context=CONTEXT, evidence=evidence)
            assert result.verified == (result.status is VerificationStatus.VERIFIED)

    def test_echoes_the_target_it_judged_against(self, provider) -> None:  # type: ignore[no-untyped-def]
        result = provider.evaluate(context=CONTEXT, evidence=PASSING)
        assert result.target == CONTEXT.target_value

    def test_attributes_the_result_to_itself(self, provider) -> None:  # type: ignore[no-untyped-def]
        result = provider.evaluate(context=CONTEXT, evidence=PASSING)
        assert result.source == provider.source

    def test_never_raises_on_malformed_evidence(self, provider) -> None:  # type: ignore[no-untyped-def]
        """Bad evidence is a verdict, not an exception: the service decides what
        becomes a 4xx, and a provider that threw would bypass that decision."""
        result = provider.evaluate(context=CONTEXT, evidence=MALFORMED)
        assert not result.verified
        assert result.reason_code

    def test_gives_a_reason_whenever_it_declines(self, provider) -> None:  # type: ignore[no-untyped-def]
        short = HealthEvidence(
            metric=ActivityKind.STEPS,
            value=Decimal("10"),
            unit="steps",
            period_start=DAY_START,
            period_end=NOW,
        )
        result = provider.evaluate(context=CONTEXT, evidence=short)
        assert not result.verified
        assert result.reason_code, "a declined result must say why"

    def test_result_is_immutable(self, provider) -> None:  # type: ignore[no-untyped-def]
        """§3.2: a recorded verdict is evidence and is never edited after the fact."""
        result = provider.evaluate(context=CONTEXT, evidence=PASSING)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.verified = False  # type: ignore[misc]
