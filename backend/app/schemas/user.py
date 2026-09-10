import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.user import OnboardingStage


class UserResponse(BaseModel):
    """`GET /me`'s shape. Deliberately trimmed versus the original Phase 0 sketch —
    no `level`/`xp_to_next_level`/`current_streak`: those need the XP/Streak/Challenge
    domains, which don't exist yet. Only fields backed by real persisted data today.
    """

    id: uuid.UUID
    email: str
    display_name: str
    avatar_media_id: uuid.UUID | None
    xp_total: int
    notification_preferences: dict[str, Any] | None
    # Where first-run onboarding left off. The client reads this instead of remembering
    # locally, so the answer survives reinstall, a second device, and logout/login.
    onboarding_stage: OnboardingStage
    onboarding_completed_at: datetime | None


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    notification_preferences: dict[str, Any] | None = None
    # Onboarding progress is client-driven — only the client knows which step the user
    # is looking at. It is deliberately *not* competitive state: nothing in scoring, XP
    # or standings reads it, so letting the client advance it grants no advantage.
    onboarding_stage: OnboardingStage | None = None
