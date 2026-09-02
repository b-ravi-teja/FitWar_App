"""Apple Health provider.

Receives evidence the iOS client already read out of HealthKit and normalized, and
decides whether it satisfies the challenge — the client never self-reports "I passed"
(Architecture §1 tenet 1, §8).

Note what is *not* here: no HealthKit types, no Apple SDK, no call to Apple. By the
time evidence reaches this file it is plain numbers and timestamps, which is exactly
why the same code path will serve Health Connect or Garmin later.
"""

from datetime import datetime
from decimal import Decimal

from app.domain.verification.evidence import HealthEvidence, validate
from app.domain.verification.metrics import METRIC_NAME, to_canonical
from app.domain.verification.result import (
    VerificationContext,
    VerificationResult,
    VerificationStatus,
)

SOURCE = "apple_health"

# Manually typed HealthKit entries are trivially forgeable — a user can open Health and
# key in 50,000 steps. §8 makes trusted source part of the verdict ("VERIFIED if the
# sample's source/device is trusted"), so hand-entered data is recorded as
# INCONCLUSIVE: kept as evidence, never credited as a pass.
USER_ENTERED_REASON = "USER_ENTERED_DATA"
TARGET_NOT_MET_REASON = "TARGET_NOT_MET"


class AppleHealthProvider:
    """Implements `domain.verification.result.VerificationProvider`."""

    source = SOURCE

    def evaluate(
        self, *, context: VerificationContext, evidence: HealthEvidence
    ) -> VerificationResult:
        metric = METRIC_NAME[context.activity]

        rejection = validate(
            evidence,
            activity=context.activity,
            day_start_at=context.day_start_at,
            day_end_at=context.day_end_at,
            now=context.now,
        )
        if rejection is not None:
            # Value is left in the submitted unit: conversion is only meaningful once
            # the unit is known to be valid, and this record exists to show what
            # arrived, not to assert a converted quantity.
            return self._build(
                context,
                metric=metric,
                value=evidence.value,
                status=VerificationStatus.REJECTED,
                verified=False,
                reason=rejection.value,
                source_timestamp=evidence.period_end,
            )

        value = to_canonical(context.activity, evidence.value, evidence.unit)

        if evidence.was_user_entered:
            return self._build(
                context,
                metric=metric,
                value=value,
                status=VerificationStatus.INCONCLUSIVE,
                verified=False,
                reason=USER_ENTERED_REASON,
                source_timestamp=evidence.period_end,
            )

        met_target = value >= context.target_value
        return self._build(
            context,
            metric=metric,
            value=value,
            # Falling short is neither an error nor a rejection of the evidence: the
            # measurement is trusted, it just hasn't reached the target yet. The day
            # stays open until its deadline so a later sync can still complete it.
            status=VerificationStatus.VERIFIED if met_target else VerificationStatus.INCONCLUSIVE,
            verified=met_target,
            reason=None if met_target else TARGET_NOT_MET_REASON,
            source_timestamp=evidence.period_end,
        )

    def _build(
        self,
        context: VerificationContext,
        *,
        metric: str,
        value: Decimal,
        status: VerificationStatus,
        verified: bool,
        reason: str | None,
        source_timestamp: datetime,
    ) -> VerificationResult:
        return VerificationResult(
            verified=verified,
            source=self.source,
            metric=metric,
            value=value,
            target=context.target_value,
            status=status,
            source_timestamp=source_timestamp,
            reason_code=reason,
        )
