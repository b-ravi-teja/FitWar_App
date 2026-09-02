"""Request/response contracts for health connections and verification.

The evidence schema is the wire form of the §8 boundary: explicit units, explicit UTC
instants, no HealthKit vocabulary. A client on any platform can fill it in, and the
server can validate every field without knowing which one did.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.domain.verification.metrics import ActivityKind
from app.models.challenge import DailyProgressStatus
from app.models.verification import (
    HealthConnectionStatus,
    HealthProvider,
    VerificationStatus,
)


class HealthConnectionResponse(BaseModel):
    id: uuid.UUID
    provider: HealthProvider
    status: HealthConnectionStatus
    # Server's own observation of when evidence last arrived — never a client claim.
    last_synced_at: datetime | None
    connected_at: datetime


class CreateHealthConnectionRequest(BaseModel):
    provider: HealthProvider


class HealthEvidenceRequest(BaseModel):
    """One aggregated measurement, already normalized by the client.

    `period_start`/`period_end` must be the exact UTC window the server published for
    the challenge day (`GET /challenges/{id}/progress/today` returns both bounds). The
    client must not derive the window from its own calendar: the challenge day belongs
    to the challenge's frozen timezone, which is frequently not the device's.
    """

    metric: ActivityKind
    value: Decimal = Field(max_digits=12, decimal_places=2)
    unit: str = Field(min_length=1, max_length=16)
    period_start: datetime
    period_end: datetime
    source_name: str | None = Field(default=None, max_length=120)
    source_bundle_id: str | None = Field(default=None, max_length=200)
    was_user_entered: bool = False

    @field_validator("period_start", "period_end")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        # A naive timestamp has no defined instant, and guessing one would be exactly
        # the device-local assumption §11 forbids.
        if value.tzinfo is None:
            raise ValueError("must include a UTC offset")
        return value


class SubmitVerificationRequest(BaseModel):
    provider: HealthProvider
    evidence: HealthEvidenceRequest


class VerificationRecordResponse(BaseModel):
    id: uuid.UUID
    provider: str
    metric: str
    value: Decimal
    target: Decimal
    status: VerificationStatus
    reason_code: str | None
    source_timestamp: datetime
    verified_at: datetime | None


class SubmitVerificationResponse(BaseModel):
    """What the Verify screen renders.

    `day_status` is the authoritative outcome — the client displays it and never
    computes completion itself.
    """

    verification: VerificationRecordResponse
    challenge_day: date
    day_status: DailyProgressStatus
    deadline_at: datetime
    # True when this repeated an already-completed day: the same result is returned
    # rather than a second one being recorded.
    idempotent_replay: bool
