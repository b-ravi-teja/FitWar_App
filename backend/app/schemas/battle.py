"""Request/response contracts for 1v1 battles.

Note what a client is never allowed to send: a score, a winner, an XP amount, a rank, a
battle status, or a participant list. The request bodies below carry an *intent*
(challenge this person, accept, decline, here is my evidence) and nothing else — every
competitive value in the responses is server-computed (Architecture §1, tenet 1).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.battle import BattleParticipantStatus, BattleStatus
from app.models.challenge import ActivityType
from app.schemas.verification import SubmitVerificationResponse


class CreateBattleRequest(BaseModel):
    """`POST /battles`. `verification_method` is absent on purpose — V1 battles verify
    from health data (ADR 0009) — and so is anything resembling a score."""

    opponent_user_id: uuid.UUID
    activity_type: ActivityType
    # Optional: the server fills in the activity's default target when omitted.
    target_value: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    duration_days: int = Field(ge=1, le=365)
    # Optional. Required only when the two players share more than one squad, in which
    # case the server answers `GROUP_REQUIRED` rather than guessing.
    group_id: uuid.UUID | None = None


class BattleSideResponse(BaseModel):
    """One player, as the other is allowed to see them (§18).

    Scores and banked days are the contest and are shared; evidence, proof media, health
    records and verification metadata are not, and have no field here to travel in.
    """

    user_id: uuid.UUID
    display_name: str
    status: BattleParticipantStatus
    score: Decimal
    days_completed: int
    is_me: bool


class BattleResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    status: BattleStatus
    activity_type: ActivityType
    target_value: Decimal
    unit: str
    day_index: int
    duration_days: int
    timezone: str
    start_at: datetime
    end_at: datetime
    completed_at: datetime | None
    # Seconds until the battle's window closes; 0 once it has. Server-computed so two
    # devices with different clocks agree on the countdown.
    time_remaining_seconds: int
    sides: list[BattleSideResponse]
    # Present only once the battle is finalized. Until then there is no winner — not a
    # provisional one, because a "current winner" is exactly the mutable source of truth
    # §8 forbids.
    winner_user_id: uuid.UUID | None
    my_outcome: str | None
    # What the ledger paid the caller for this win. `null` for the loser and while the
    # battle is unfinished — a zero would render as "you earned 0 XP", which is a
    # different and untrue claim.
    my_xp_awarded: int | None


class RivalResponse(BaseModel):
    user_id: uuid.UUID
    display_name: str
    wins_against: int
    losses_against: int
    # Set when a battle with this rival is already pending or active, so the UI offers
    # "VIEW" instead of a "CHALLENGE" the server would reject.
    live_battle_id: uuid.UUID | None


class SubmitBattleEvidenceResponse(BaseModel):
    """The verification verdict plus the battle it changed.

    Same verification payload the challenge endpoint returns — one contract, one client
    decoder, no battle-specific verification shape.
    """

    verification: SubmitVerificationResponse
    battle: BattleResponse
