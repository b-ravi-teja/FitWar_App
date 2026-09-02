"""Game-system contracts: leaderboard, XP/level, and the per-day competitive result."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.challenge import ParticipantOutcome, ParticipantStatus
from app.models.game import XPReason


class DayResolutionResponse(BaseModel):
    """What a successful verification did competitively. Server-computed in full — the
    client renders these numbers and derives none of them (Architecture §1)."""

    xp_awarded: int
    completion_xp: int
    streak_bonus_xp: int
    score_delta: Decimal
    current_streak: int


class LeaderboardEntryResponse(BaseModel):
    rank: int
    user_id: uuid.UUID
    display_name: str
    score: Decimal
    current_streak: int
    status: ParticipantStatus
    outcome: ParticipantOutcome | None
    is_me: bool


class LeaderboardResponse(BaseModel):
    """`rank` is assigned at read time from the frozen tie-break and never persisted
    (Architecture §3.2). `is_final` says the challenge has closed, so these standings
    are immutable."""

    challenge_id: uuid.UUID
    game_mode: str
    is_final: bool
    entries: list[LeaderboardEntryResponse]


class WarningResponse(BaseModel):
    challenge_day: date
    reason: str
    created_at: datetime


class MyChallengeGameStateResponse(BaseModel):
    """The caller's own competitive standing in one challenge."""

    challenge_id: uuid.UUID
    rank: int | None
    score: Decimal
    current_streak: int
    longest_streak: int
    consecutive_misses: int
    status: ParticipantStatus
    outcome: ParticipantOutcome | None
    warnings: list[WarningResponse]
    eliminated_at: datetime | None


class XPTransactionResponse(BaseModel):
    id: uuid.UUID
    amount: int
    reason: XPReason
    created_at: datetime


class XPSummaryResponse(BaseModel):
    """Level is derived from `xp_total` by the server; the client never computes it."""

    xp_total: int
    level: int
    xp_into_level: int
    xp_to_next_level: int
    transactions: list[XPTransactionResponse]
