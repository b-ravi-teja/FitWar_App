import uuid
from typing import Any

from pydantic import BaseModel, Field


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


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    notification_preferences: dict[str, Any] | None = None
