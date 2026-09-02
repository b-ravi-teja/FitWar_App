"""Persistence for chat messages and reactions."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.media import GroupMessage, MessageReaction, MessageType
from app.models.user import User, UserProfile


class ChatRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        *,
        group_id: uuid.UUID,
        sender_id: uuid.UUID | None,
        content: str,
        message_type: MessageType = MessageType.TEXT,
    ) -> GroupMessage:
        message = GroupMessage(
            group_id=group_id,
            sender_id=sender_id,
            content=content,
            message_type=message_type,
            # Set explicitly rather than leaning on the column's `now()` default:
            # Postgres' now() is *transaction* start time, so messages written in one
            # transaction would share a timestamp and have no defined order.
            created_at=datetime.now(UTC),
        )
        self._session.add(message)
        await self._session.flush()
        return message

    async def page(
        self,
        group_id: uuid.UUID,
        *,
        before: datetime | None,
        before_id: uuid.UUID | None,
        limit: int,
    ) -> list[tuple[GroupMessage, str | None]]:
        """Newest first, keyset-paginated on `(created_at, id)`.

        The id is part of the cursor because timestamps tie: Postgres' `now()` is
        transaction-start time, so messages written together share one value, and a
        `created_at <`  cursor alone would skip every tied row and stall the walk.
        """
        statement = (
            select(GroupMessage, UserProfile.display_name)
            .outerjoin(User, User.id == GroupMessage.sender_id)
            .outerjoin(UserProfile, UserProfile.user_id == User.id)
            .where(
                GroupMessage.group_id == group_id,
                GroupMessage.deleted_at.is_(None),
            )
            .order_by(GroupMessage.created_at.desc(), GroupMessage.id.desc())
            .limit(limit)
        )
        if before is not None:
            statement = (
                statement.where(
                    tuple_(GroupMessage.created_at, GroupMessage.id)
                    < (before, before_id)
                )
                if before_id is not None
                else statement.where(GroupMessage.created_at < before)
            )
        result = await self._session.execute(statement)
        return [(row[0], row[1]) for row in result.all()]

    async def group_of(self, message_id: uuid.UUID) -> uuid.UUID | None:
        result = await self._session.execute(
            select(GroupMessage.group_id).where(GroupMessage.id == message_id)
        )
        return result.scalar_one_or_none()

    async def add_reaction(
        self, message_id: uuid.UUID, user_id: uuid.UUID, emoji: str
    ) -> bool:
        """True if this call created it. ON CONFLICT DO NOTHING against
        UNIQUE(message, user, emoji) makes a repeated add a no-op without a pre-check race."""
        statement = (
            pg_insert(MessageReaction)
            .values(
                id=uuid.uuid4(), message_id=message_id, user_id=user_id, emoji=emoji
            )
            .on_conflict_do_nothing(constraint="uq_message_reaction")
            .returning(MessageReaction.id)
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none() is not None

    async def remove_reaction(
        self, message_id: uuid.UUID, user_id: uuid.UUID, emoji: str
    ) -> bool:
        result = await self._session.execute(
            select(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == user_id,
                MessageReaction.emoji == emoji,
            )
        )
        reaction = result.scalar_one_or_none()
        if reaction is None:
            return False
        await self._session.delete(reaction)
        return True

    async def reactions_for(
        self, message_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[MessageReaction]]:
        if not message_ids:
            return {}
        result = await self._session.execute(
            select(MessageReaction).where(MessageReaction.message_id.in_(message_ids))
        )
        grouped: dict[uuid.UUID, list[MessageReaction]] = {}
        for reaction in result.scalars().all():
            grouped.setdefault(reaction.message_id, []).append(reaction)
        return grouped
