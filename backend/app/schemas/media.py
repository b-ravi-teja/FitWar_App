"""Media, proof-review and chat contracts."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.models.media import MediaStatus, MessageType
from app.models.verification import VerificationStatus


class PrepareUploadRequest(BaseModel):
    # The client declares intent; the server chooses the key and enforces the limits.
    content_type: str = Field(min_length=1, max_length=80)


class PresignedUploadResponse(BaseModel):
    """A single-object, expiring write grant. The client never holds bucket credentials
    (§34).

    `method` says which of the two upload shapes this grant is. `POST`: send a multipart
    form to `url` carrying every entry of `fields` verbatim, plus the file. `PUT`: send
    the bytes as the request body with `headers` applied and no form encoding — the shape
    Cloudflare R2 requires, since it does not implement S3 PostObject.

    Both default to the POST shape so a client written before `method` existed keeps
    working against a POST-mode deployment unchanged.
    """

    media_id: uuid.UUID
    url: str
    fields: dict[str, str]
    expires_in_seconds: int
    max_bytes: int
    method: str = "POST"
    headers: dict[str, str] = Field(default_factory=dict)


class MediaAssetResponse(BaseModel):
    id: uuid.UUID
    status: MediaStatus
    content_type: str
    size_bytes: int | None
    # Null once the object has been deleted by retention — the UI shows "no longer
    # available" rather than a player that will never load (§27).
    playback_url: str | None
    expires_at: datetime | None
    object_deleted_at: datetime | None


class PendingProofResponse(BaseModel):
    verification_record_id: uuid.UUID
    participant_user_id: uuid.UUID
    participant_display_name: str
    challenge_day: datetime | None
    claimed_value: Decimal
    target: Decimal
    submitted_at: datetime
    media_id: uuid.UUID | None
    media_available: bool


class ReviewProofRequest(BaseModel):
    approve: bool
    # Optional context for a rejection; never shown as the reason a day failed, which is
    # decided by the deadline rules, not by copy.
    note: str | None = Field(default=None, max_length=500)


class ReviewProofResponse(BaseModel):
    verification_record_id: uuid.UUID
    status: VerificationStatus
    reviewed_at: datetime | None
    # True when the proof was already resolved — the decision is returned unchanged
    # rather than applied twice.
    already_resolved: bool
    xp_awarded: int | None
    current_streak: int | None


class ReactionSummary(BaseModel):
    emoji: str
    count: int
    reacted_by_me: bool


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    sender_id: uuid.UUID | None
    sender_display_name: str | None
    content: str
    message_type: MessageType
    created_at: datetime
    reactions: list[ReactionSummary]


class ChatPageResponse(BaseModel):
    """Newest-first page.

    The cursor is a pair: pass `next_cursor` as `before` and `next_cursor_id` as
    `before_id`. Both are needed because timestamps tie — see `ChatRepository.page`.
    """

    items: list[ChatMessageResponse]
    next_cursor: datetime | None
    next_cursor_id: uuid.UUID | None = None


class PostMessageRequest(BaseModel):
    """`min_length` alone is not enough: it counts characters, so "   " passes it and
    persists a message that renders as an empty bubble nobody can delete. The content is
    stripped first and then required to be non-empty."""

    content: Annotated[str, StringConstraints(strip_whitespace=True)] = Field(
        min_length=1, max_length=1000
    )


class ReactionRequest(BaseModel):
    emoji: str = Field(min_length=1, max_length=16)
    add: bool = True
