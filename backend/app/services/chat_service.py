"""Group chat and reactions (Architecture §10, §16).

Deliberately small: text, reactions, and system messages the game emits. Not a messaging
platform — no voice, no DMs, no public rooms (§15).

Postgres is the durable source of truth. Redis is transport only: the message is
persisted **first**, then published, so a Redis outage costs realtime delivery and never
a message (§22).
"""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.realtime import group_channel, publish_realtime
from app.models.media import GroupMessage, MessageReaction, MessageType
from app.repositories.chat import ChatRepository

logger = get_logger(__name__)

# Reactions are a fixed, small set — the design shows emoji chips, not a picker, and an
# open field would be a moderation surface V1 doesn't need (§18).
ALLOWED_REACTIONS = frozenset({"🔥", "💪", "👏", "😤", "💀"})

MAX_PAGE_SIZE = 50


class ChatService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = ChatRepository(session)

    async def history(
        self,
        group_id: uuid.UUID,
        *,
        cursor: datetime | None,
        cursor_id: uuid.UUID | None,
        limit: int,
    ) -> tuple[list[tuple[GroupMessage, str | None]], tuple[datetime, uuid.UUID] | None]:
        """A page of history, newest first, with the cursor for the next page.

        Keyset pagination on `created_at` rather than OFFSET: the index is
        (group_id, created_at), and an offset scan degrades as history grows (§16).
        """
        capped = max(1, min(limit, MAX_PAGE_SIZE))
        rows = await self._repo.page(
            group_id, before=cursor, before_id=cursor_id, limit=capped + 1
        )
        has_more = len(rows) > capped
        page = rows[:capped]
        last = page[-1][0] if page else None
        next_cursor = (last.created_at, last.id) if has_more and last else None
        return page, next_cursor

    async def post(
        self, *, group_id: uuid.UUID, sender_id: uuid.UUID, content: str
    ) -> GroupMessage:
        message = await self._repo.add(
            group_id=group_id, sender_id=sender_id, content=content.strip()
        )
        await self._session.flush()
        # Published after the row exists. If this fails, the message is still readable
        # over REST — realtime is additive, never the record (§20).
        await publish_realtime(
            group_channel(group_id),
            {
                "type": "chat_message",
                "message_id": str(message.id),
                "group_id": str(group_id),
                "sender_id": str(sender_id),
                "content": message.content,
                "created_at": message.created_at.isoformat(),
            },
        )
        return message

    async def post_system(self, *, group_id: uuid.UUID, content: str) -> GroupMessage:
        """A game event rendered into the feed.

        The game system decides the event happened; chat only presents it (§19), which
        is why nothing here inspects challenges or scores.
        """
        message = await self._repo.add(
            group_id=group_id,
            sender_id=None,
            content=content,
            message_type=MessageType.SYSTEM,
        )
        await self._session.flush()
        await publish_realtime(
            group_channel(group_id),
            {
                "type": "system_message",
                "message_id": str(message.id),
                "group_id": str(group_id),
                "content": content,
                "created_at": message.created_at.isoformat(),
            },
        )
        return message

    async def react(
        self, *, message_id: uuid.UUID, user_id: uuid.UUID, emoji: str, add: bool
    ) -> bool:
        """Add or remove one reaction. Idempotent in both directions.

        UNIQUE(message, user, emoji) makes a repeated add a no-op at the database level,
        and removing an absent reaction is simply nothing to delete — so a double-tap
        converges on the same state either way (§18).
        """
        if add:
            created = await self._repo.add_reaction(message_id, user_id, emoji)
        else:
            created = await self._repo.remove_reaction(message_id, user_id, emoji)
        await self._session.flush()

        group_id = await self._repo.group_of(message_id)
        if group_id is not None:
            await publish_realtime(
                group_channel(group_id),
                {
                    "type": "reaction_changed",
                    "message_id": str(message_id),
                    "user_id": str(user_id),
                    "emoji": emoji,
                    "added": add,
                },
            )
        return created

    async def group_of(self, message_id: uuid.UUID) -> uuid.UUID | None:
        return await self._repo.group_of(message_id)

    async def reactions_for(
        self, message_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[MessageReaction]]:
        return await self._repo.reactions_for(message_ids)
