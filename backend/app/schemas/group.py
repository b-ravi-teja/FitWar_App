import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.group import GroupMemberStatus, GroupRole


class GroupSummaryResponse(BaseModel):
    """A row in the Groups List screen (§20.7)."""

    id: uuid.UUID
    name: str
    timezone: str
    member_count: int
    active_challenge_count: int


class GroupResponse(BaseModel):
    id: uuid.UUID
    name: str
    timezone: str
    privacy: str
    owner_id: uuid.UUID
    member_count: int
    active_challenge_count: int
    created_at: datetime
    # Only ever returned to an active member — `GET /groups/{id}` is membership-gated,
    # so the code is never exposed to someone who couldn't already invite others.
    join_code: str
    my_role: GroupRole


class CreateGroupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # IANA identifier — validated in the service, not here, so the failure surfaces as a
    # domain error with a stable `code` rather than a generic 422.
    timezone: str = Field(min_length=1, max_length=64)


class UpdateGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)


class JoinGroupRequest(BaseModel):
    join_code: str = Field(min_length=1, max_length=12)


class GroupMemberResponse(BaseModel):
    """A Roster row. `current_streak` / `warning_count` / `is_eliminated_in_active_challenge`
    from the original API sketch are deliberately absent: streaks and warnings are Phase 5/6,
    and returning zeros would render as real data in the UI.
    """

    user_id: uuid.UUID
    display_name: str
    role: GroupRole
    status: GroupMemberStatus
    joined_at: datetime
    active_challenge_count: int


class UpdateGroupMemberRequest(BaseModel):
    role: GroupRole | None = None
    status: GroupMemberStatus | None = None


class GroupActivityEntry(BaseModel):
    """One line in the group Feed tab, derived from records Phase 3 actually writes."""

    kind: str
    actor_display_name: str
    text: str
    occurred_at: datetime
