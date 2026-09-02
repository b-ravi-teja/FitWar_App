"""The verification abstraction (Architecture §8).

Challenge completion logic consumes `VerificationResult` and nothing else. It never
learns whether the number came from HealthKit, a reviewed video, or a future GPS
track — which is precisely what lets a new provider be added without touching
`challenge_service.py`.

Pure Python, no framework imports. `VerificationContext` exists because the frozen
sketch in §8 passes a `ChallengeParticipant` ORM object to `submit()`; doing that
literally would drag SQLAlchemy into the domain layer and break the harder rule
(§2, "domain has zero framework imports"). §8 labels its snippet "conceptual shape,
not final code", so the context carries the same facts as plain values instead.
"""

import enum
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol

from app.domain.verification.evidence import HealthEvidence
from app.domain.verification.metrics import ActivityKind


class VerificationStatus(enum.StrEnum):
    VERIFIED = "verified"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class VerificationContext:
    """Everything a provider needs about the challenge, as plain values."""

    activity: ActivityKind
    target_value: Decimal
    challenge_day: date
    # The exact UTC span of the challenge day, resolved server-side from the
    # challenge's frozen IANA timezone (Architecture §11). Providers compare evidence
    # against this, never against a device-local calendar day.
    day_start_at: datetime
    day_end_at: datetime
    # Supplied by the caller rather than read from the clock, so providers stay pure
    # and a test can evaluate any instant deterministically.
    now: datetime


@dataclass(frozen=True)
class VerificationResult:
    """A provider's verdict. Immutable — once persisted it is evidence of what was
    decided, and is never edited (Architecture §3.2)."""

    verified: bool
    source: str
    metric: str
    value: Decimal
    target: Decimal
    status: VerificationStatus
    # When the activity happened, not when it was submitted.
    source_timestamp: datetime
    # Why a non-verified result came out that way, as a stable machine-readable code.
    reason_code: str | None = None
    evidence_ref: str | None = None


class VerificationProvider(Protocol):
    """Implemented once per evidence source. See `integrations/verification_providers/`."""

    source: str

    def evaluate(
        self, *, context: VerificationContext, evidence: HealthEvidence
    ) -> VerificationResult: ...
