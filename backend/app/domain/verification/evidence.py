"""Normalized evidence — the boundary type that keeps HealthKit out of the backend.

The iOS app reads `HKQuantitySample`s and reduces them to this before transmitting.
Nothing HealthKit-shaped crosses the wire: no sample objects, no HKUnit, no raw health
records beyond the single aggregate the challenge actually needs. That is the whole
point of the boundary — the server could not import HealthKit if it wanted to, and a
future Health Connect or Garmin client fills in exactly the same shape.

Pure Python. Validation here is total: the server re-derives every judgement from these
values and never trusts a client-computed verdict.
"""

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.domain.verification.metrics import (
    ActivityKind,
    is_health_readable,
    is_supported_unit,
)

# Allowance for ordinary clock drift between device and server. Wide enough that an
# honest phone a couple of minutes fast is not rejected, far too narrow to shift a
# submission into a different challenge day.
CLOCK_SKEW_TOLERANCE = timedelta(minutes=5)


@dataclass(frozen=True)
class HealthEvidence:
    """One aggregated measurement for one challenge day."""

    metric: ActivityKind
    value: Decimal
    unit: str
    # The UTC span the client aggregated over. The server checks this against the
    # challenge day it computed itself.
    period_start: datetime
    period_end: datetime
    # HealthKit source attribution, kept for auditability. Never proof on its own — the
    # server does not trust the client's claim about where the data came from.
    source_name: str | None = None
    source_bundle_id: str | None = None
    # HKMetadataKeyWasUserEntered: the user typed this number in by hand rather than a
    # device recording it.
    was_user_entered: bool = False


class EvidenceRejection(enum.StrEnum):
    """Why evidence could not be accepted. Stable codes — clients switch on these."""

    INCOMPATIBLE_METRIC = "INCOMPATIBLE_METRIC"
    UNSUPPORTED_UNIT = "UNSUPPORTED_UNIT"
    NEGATIVE_VALUE = "NEGATIVE_VALUE"
    OUTSIDE_CHALLENGE_DAY = "OUTSIDE_CHALLENGE_DAY"
    PERIOD_IN_FUTURE = "PERIOD_IN_FUTURE"
    INVERTED_PERIOD = "INVERTED_PERIOD"
    METRIC_NOT_HEALTH_READABLE = "METRIC_NOT_HEALTH_READABLE"


def period_within_day(
    evidence: HealthEvidence, day_start_at: datetime, day_end_at: datetime
) -> bool:
    """Does the measured span sit inside the challenge day the server resolved?

    This is the check that makes timezone handling safe. A device in `America/Chicago`
    submitting for a challenge frozen to `Asia/Kolkata` will have aggregated over the
    wrong absolute instants, and that is caught here rather than silently credited to
    the wrong day.
    """
    return (
        evidence.period_start >= day_start_at - CLOCK_SKEW_TOLERANCE
        and evidence.period_end <= day_end_at + CLOCK_SKEW_TOLERANCE
    )


def validate(
    evidence: HealthEvidence,
    *,
    activity: ActivityKind,
    day_start_at: datetime,
    day_end_at: datetime,
    now: datetime,
) -> EvidenceRejection | None:
    """Return the reason this evidence is unusable, or `None` if it is well-formed.

    Deliberately returns rather than raises: the caller decides which rejections are a
    client error (wrong unit — a 4xx) and which are a legitimate attempt that simply
    cannot be credited, and that decision is not the domain's to make.
    """
    if evidence.metric is not activity:
        return EvidenceRejection.INCOMPATIBLE_METRIC
    if not is_health_readable(activity):
        return EvidenceRejection.METRIC_NOT_HEALTH_READABLE
    if not is_supported_unit(activity, evidence.unit):
        return EvidenceRejection.UNSUPPORTED_UNIT
    if evidence.value < 0:
        return EvidenceRejection.NEGATIVE_VALUE
    if evidence.period_end < evidence.period_start:
        return EvidenceRejection.INVERTED_PERIOD
    if evidence.period_end > now + CLOCK_SKEW_TOLERANCE:
        return EvidenceRejection.PERIOD_IN_FUTURE
    if not period_within_day(evidence, day_start_at, day_end_at):
        return EvidenceRejection.OUTSIDE_CHALLENGE_DAY
    return None
