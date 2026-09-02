import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.challenge import (
    ActivityType,
    ChallengeStatus,
    DailyProgressStatus,
    GameMode,
    ParticipantOutcome,
    ParticipantStatus,
    VerificationMethod,
)


class CreateChallengeRequest(BaseModel):
    """The 5-step create flow's final submission.

    No `status` field, deliberately: the server decides whether a new challenge is DRAFT
    or ACTIVE from `start_at` against the clock (Architecture §1 tenet 1 — the client
    sends configuration, never a resulting state).
    """

    name: str = Field(min_length=1, max_length=80)
    activity_type: ActivityType
    target_value: Decimal = Field(gt=0)
    unit: str = Field(min_length=1, max_length=24)
    game_mode: GameMode
    verification_method: VerificationMethod
    duration_days: int = Field(ge=1, le=365)
    participant_limit: int | None = Field(default=None, ge=2)
    start_at: datetime | None = None


class UpdateChallengeRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    target_value: Decimal | None = Field(default=None, gt=0)


class ChallengeParticipantResponse(BaseModel):
    """`rank` is computed at read time from score ordering and never persisted
    (Architecture §3.2). Score is genuinely 0 for everyone until verification lands in
    Phase 4 — the client renders that as a pending state rather than a standing.
    """

    user_id: uuid.UUID
    display_name: str
    status: ParticipantStatus
    outcome: ParticipantOutcome | None
    current_score: Decimal
    current_streak: int
    rank: int
    joined_at: datetime


class ChallengeSummaryResponse(BaseModel):
    """A card in the Challenges list / Home. Progress fields describe the *day*, not a
    verified metric — Phase 3 has no verified values to report.
    """

    id: uuid.UUID
    group_id: uuid.UUID
    name: str
    activity_type: ActivityType
    game_mode: GameMode
    status: ChallengeStatus
    target_value: Decimal
    unit: str
    day_index: int
    duration_days: int
    participant_count: int
    my_status: ParticipantStatus | None


class ChallengeDetailResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    creator_id: uuid.UUID
    name: str
    activity_type: ActivityType
    game_mode: GameMode
    verification_method: VerificationMethod
    status: ChallengeStatus
    target_value: Decimal
    unit: str
    timezone: str
    start_at: datetime
    end_at: datetime
    day_index: int
    duration_days: int
    participant_count: int
    participant_limit: int | None
    failure_rule: str
    my_status: ParticipantStatus | None
    participants: list[ChallengeParticipantResponse]


class DailyProgressResponse(BaseModel):
    """`current_value` is absent, not zero.

    A zero would render in the UI as "you've done nothing today," which isn't what
    PENDING means — it means nothing has been measured yet, because verification is
    Phase 4. The client shows a pending state off `status`.
    """

    challenge_day: date
    day_index: int
    status: DailyProgressStatus
    target: Decimal
    unit: str
    # Both bounds of the challenge day in UTC, resolved from the challenge's frozen
    # timezone. `window_start_at` is published rather than left for the client to
    # compute: a DST day is 23 or 25 hours long, so `deadline_at - 24h` is wrong twice
    # a year, and a client that guessed would query health data over the wrong span.
    window_start_at: datetime
    deadline_at: datetime
    completed_at: datetime | None
