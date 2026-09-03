import uuid
from datetime import UTC, datetime

from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.challenge import Challenge, ChallengeStatus
from app.models.group import Group, GroupMember, GroupMemberStatus, GroupRole
from app.models.user import User, UserProfile


class GroupRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _alive() -> Select[tuple[Group]]:
        return select(Group).where(Group.deleted_at.is_(None))

    async def get_by_id(self, group_id: uuid.UUID) -> Group | None:
        result = await self._session.execute(self._alive().where(Group.id == group_id))
        return result.scalar_one_or_none()

    async def get_by_join_code(self, join_code: str) -> Group | None:
        result = await self._session.execute(self._alive().where(Group.join_code == join_code))
        return result.scalar_one_or_none()

    async def join_code_exists(self, join_code: str) -> bool:
        result = await self._session.execute(
            select(Group.id).where(Group.join_code == join_code).limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def create(
        self, *, owner_id: uuid.UUID, name: str, timezone: str, join_code: str
    ) -> Group:
        group = Group(owner_id=owner_id, name=name, timezone=timezone, join_code=join_code)
        self._session.add(group)
        await self._session.flush()
        return group

    async def update(self, group: Group, *, name: str | None, timezone: str | None) -> Group:
        if name is not None:
            group.name = name
        if timezone is not None:
            group.timezone = timezone
        await self._session.flush()
        return group

    async def list_for_user(self, user_id: uuid.UUID) -> list[tuple[Group, int, int]]:
        """Groups the caller actively belongs to, with member and active-challenge counts.

        The two counts are correlated scalar subqueries rather than joins with GROUP BY:
        the Groups List screen needs both numbers per row, and joining two independent
        one-to-many relations in a single query multiplies the rows.
        """
        # Aliased, and explicitly correlated to Group only: the outer query already
        # joins `group_member` for the membership filter, and without an alias
        # SQLAlchemy correlates that same table into the subquery, leaving it with no
        # FROM clause at all.
        counted_member = aliased(GroupMember)
        member_count = (
            select(func.count())
            .select_from(counted_member)
            .where(
                counted_member.group_id == Group.id,
                counted_member.status == GroupMemberStatus.ACTIVE,
            )
            .correlate(Group)
            .scalar_subquery()
        )
        active_challenge_count = (
            select(func.count())
            .select_from(Challenge)
            .where(Challenge.group_id == Group.id, Challenge.status == ChallengeStatus.ACTIVE)
            .correlate(Group)
            .scalar_subquery()
        )
        stmt = (
            select(Group, member_count, active_challenge_count)
            .join(GroupMember, GroupMember.group_id == Group.id)
            .where(
                GroupMember.user_id == user_id,
                GroupMember.status == GroupMemberStatus.ACTIVE,
                Group.deleted_at.is_(None),
            )
            .order_by(Group.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def counts_for(self, group_id: uuid.UUID) -> tuple[int, int]:
        members = await self._session.execute(
            select(func.count())
            .select_from(GroupMember)
            .where(
                GroupMember.group_id == group_id, GroupMember.status == GroupMemberStatus.ACTIVE
            )
        )
        challenges = await self._session.execute(
            select(func.count())
            .select_from(Challenge)
            .where(Challenge.group_id == group_id, Challenge.status == ChallengeStatus.ACTIVE)
        )
        return members.scalar_one(), challenges.scalar_one()


class GroupMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMember | None:
        result = await self._session.execute(
            select(GroupMember).where(
                GroupMember.group_id == group_id, GroupMember.user_id == user_id
            )
        )
        return result.scalar_one_or_none()

    async def get_active(self, group_id: uuid.UUID, user_id: uuid.UUID) -> GroupMember | None:
        member = await self.get(group_id, user_id)
        return member if member and member.status == GroupMemberStatus.ACTIVE else None

    async def shared_group_ids(self, a: uuid.UUID, b: uuid.UUID) -> list[uuid.UUID]:
        """Groups where both users are active members.

        Backs the battle rule "you may challenge someone you share a squad with" — a
        self-join rather than two round trips, so the answer is one consistent read.
        """
        theirs = GroupMember.__table__.alias("theirs")
        result = await self._session.execute(
            select(GroupMember.group_id)
            .join(
                theirs,
                (theirs.c.group_id == GroupMember.group_id)
                & (theirs.c.user_id == b)
                & (theirs.c.status == GroupMemberStatus.ACTIVE),
            )
            .where(
                GroupMember.user_id == a,
                GroupMember.status == GroupMemberStatus.ACTIVE,
            )
            .order_by(GroupMember.group_id)
        )
        return list(result.scalars().all())

    async def add(
        self, *, group_id: uuid.UUID, user_id: uuid.UUID, role: GroupRole
    ) -> GroupMember:
        member = GroupMember(group_id=group_id, user_id=user_id, role=role)
        self._session.add(member)
        await self._session.flush()
        return member

    async def set_status(self, member: GroupMember, status: GroupMemberStatus) -> GroupMember:
        member.status = status
        if status == GroupMemberStatus.ACTIVE:
            member.joined_at = datetime.now(UTC)
        await self._session.flush()
        return member

    async def set_role(self, member: GroupMember, role: GroupRole) -> GroupMember:
        member.role = role
        await self._session.flush()
        return member

    async def roster(self, group_id: uuid.UUID) -> list[tuple[GroupMember, str]]:
        """Active roster with display names, ordered owner → admin → member, then join time."""
        # Explicit rank, not `ORDER BY role` — the enum's stored values sort
        # alphabetically ("admin" < "member" < "owner"), which is not the intended order.
        role_rank = case(
            (GroupMember.role == GroupRole.OWNER, 0),
            (GroupMember.role == GroupRole.ADMIN, 1),
            else_=2,
        )
        stmt = (
            select(GroupMember, UserProfile.display_name)
            .join(User, User.id == GroupMember.user_id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(
                GroupMember.group_id == group_id,
                GroupMember.status == GroupMemberStatus.ACTIVE,
            )
            .order_by(role_rank, GroupMember.joined_at.asc())
        )
        result = await self._session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]
