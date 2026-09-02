"""Group chat endpoints. Membership is enforced server-side on every route (§17)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import ChatServiceDep, GroupMemberContext
from app.domain.chat.exceptions import MessageNotFoundError, ReactionNotAllowedError
from app.schemas.media import (
    ChatMessageResponse,
    ChatPageResponse,
    PostMessageRequest,
    ReactionRequest,
    ReactionSummary,
)
from app.services.chat_service import ALLOWED_REACTIONS

router = APIRouter(prefix="/groups", tags=["chat"])


def _summarize(reactions, me: uuid.UUID) -> list[ReactionSummary]:  # type: ignore[no-untyped-def]
    counts: dict[str, list[uuid.UUID]] = {}
    for reaction in reactions:
        counts.setdefault(reaction.emoji, []).append(reaction.user_id)
    return [
        ReactionSummary(emoji=emoji, count=len(users), reacted_by_me=me in users)
        for emoji, users in sorted(counts.items())
    ]


@router.get("/{group_id}/messages", response_model=ChatPageResponse)
async def list_messages(
    context: GroupMemberContext,
    chat: ChatServiceDep,
    before: Annotated[datetime | None, Query()] = None,
    before_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 30,
) -> ChatPageResponse:
    """Newest-first history. `GroupMemberContext` is what blocks non-members and anyone
    who has left — the check hits the database, never the UI."""
    rows, next_cursor = await chat.history(
        context.group.id, cursor=before, cursor_id=before_id, limit=limit
    )
    reactions = await chat.reactions_for([message.id for message, _ in rows])
    return ChatPageResponse(
        items=[
            ChatMessageResponse(
                id=message.id,
                group_id=message.group_id,
                sender_id=message.sender_id,
                sender_display_name=display_name,
                content=message.content,
                message_type=message.message_type,
                created_at=message.created_at,
                reactions=_summarize(reactions.get(message.id, []), context.user.id),
            )
            for message, display_name in rows
        ],
        next_cursor=next_cursor[0] if next_cursor else None,
        next_cursor_id=next_cursor[1] if next_cursor else None,
    )


@router.post(
    "/{group_id}/messages",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    body: PostMessageRequest, context: GroupMemberContext, chat: ChatServiceDep
) -> ChatMessageResponse:
    message = await chat.post(
        group_id=context.group.id, sender_id=context.user.id, content=body.content
    )
    return ChatMessageResponse(
        id=message.id,
        group_id=message.group_id,
        sender_id=message.sender_id,
        sender_display_name=None,
        content=message.content,
        message_type=message.message_type,
        created_at=message.created_at,
        reactions=[],
    )


@router.post(
    "/{group_id}/messages/{message_id}/reactions",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def react(
    message_id: uuid.UUID,
    body: ReactionRequest,
    context: GroupMemberContext,
    chat: ChatServiceDep,
) -> None:
    """Add or remove one reaction. Idempotent in both directions (§18)."""
    if body.emoji not in ALLOWED_REACTIONS:
        raise ReactionNotAllowedError("That reaction isn't available.")
    # The message must live in the group the caller is authorized for; otherwise a
    # member of any group could react to any message id they guessed.
    if await chat.group_of(message_id) != context.group.id:
        raise MessageNotFoundError("No such message.")
    await chat.react(
        message_id=message_id, user_id=context.user.id, emoji=body.emoji, add=body.add
    )
