"""Group use cases: create, join by invite code, leave, roster, member administration.

All domain rules live here or in `domain/groups`; routes stay a translation layer.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.challenges.challenge_day import is_valid_timezone
from app.domain.groups.exceptions import (
    AlreadyGroupMemberError,
    CannotModifyOwnerError,
    GroupNotFoundError,
    InvalidJoinCodeError,
    InvalidTimezoneError,
    MemberRemovedError,
    NotAGroupMemberError,
    OwnerCannotLeaveError,
)
from app.domain.groups.join_code import generate_join_code, normalize_join_code
from app.models.group import Group, GroupMember, GroupMemberStatus, GroupRole
from app.repositories.groups import GroupMemberRepository, GroupRepository
from app.repositories.users import UserRepository

# Codes are 5 characters from a 32-symbol alphabet (~33M combinations); a collision is
# already unlikely, and retrying a handful of times makes it effectively impossible
# without needing a wider code than the design shows.
_JOIN_CODE_ATTEMPTS = 8


class GroupService:
    def __init__(self, session: AsyncSession) -> None:
        self._groups = GroupRepository(session)
        self._members = GroupMemberRepository(session)
        self._users = UserRepository(session)

    async def list_for_user(self, user_id: uuid.UUID) -> list[tuple[Group, int, int]]:
        return await self._groups.list_for_user(user_id)

    async def create(self, *, owner_id: uuid.UUID, name: str, timezone: str) -> Group:
        self._require_valid_timezone(timezone)
        group = await self._groups.create(
            owner_id=owner_id,
            name=name,
            timezone=timezone,
            join_code=await self._unique_join_code(),
        )
        await self._members.add(group_id=group.id, user_id=owner_id, role=GroupRole.OWNER)
        return group

    async def get_for_member(self, group_id: uuid.UUID, user_id: uuid.UUID) -> Group:
        group = await self._groups.get_by_id(group_id)
        if group is None:
            raise GroupNotFoundError(f"No group {group_id}.")
        if await self._members.get_active(group_id, user_id) is None:
            raise NotAGroupMemberError("Only active members can view this group.")
        return group

    async def update(
        self, group: Group, *, name: str | None, timezone: str | None
    ) -> Group:
        if timezone is not None:
            self._require_valid_timezone(timezone)
        # Editing the group's timezone never reaches challenges already created from it —
        # each one snapshotted its own copy at creation (Architecture §11).
        return await self._groups.update(group, name=name, timezone=timezone)

    async def counts_for(self, group_id: uuid.UUID) -> tuple[int, int]:
        return await self._groups.counts_for(group_id)

    async def roster(self, group_id: uuid.UUID) -> list[tuple[GroupMember, str]]:
        return await self._members.roster(group_id)

    async def join_by_code(
        self, *, user_id: uuid.UUID, join_code: str, group_id: uuid.UUID | None = None
    ) -> GroupMember:
        """Join via invite code. Idempotent for an existing active member.

        `group_id` is supplied when the caller came in through `/groups/{id}/join` (an
        invite link, which carries both); the code must then belong to that group, so a
        valid code for a *different* group can't be used to join this one.
        """
        group = await self._groups.get_by_join_code(normalize_join_code(join_code))
        if group is None or (group_id is not None and group.id != group_id):
            raise InvalidJoinCodeError("That invite code doesn't match a group.")

        existing = await self._members.get(group.id, user_id)
        if existing is None:
            return await self._members.add(
                group_id=group.id, user_id=user_id, role=GroupRole.MEMBER
            )
        if existing.status == GroupMemberStatus.ACTIVE:
            # Not an error the client must recover from — re-tapping an invite link is a
            # normal thing to do, so this reports a conflict the UI can treat as success.
            raise AlreadyGroupMemberError("You're already in this group.")
        if existing.status == GroupMemberStatus.REMOVED:
            raise MemberRemovedError("An admin removed you from this group.")
        return await self._members.set_status(existing, GroupMemberStatus.ACTIVE)

    async def leave(self, *, group: Group, member: GroupMember) -> None:
        if member.role == GroupRole.OWNER:
            raise OwnerCannotLeaveError(
                "The owner can't leave their own group. Transfer ownership first."
            )
        await self._members.set_status(member, GroupMemberStatus.LEFT)

    async def update_member(
        self,
        *,
        group: Group,
        actor: GroupMember,
        target_user_id: uuid.UUID,
        role: GroupRole | None,
        status: GroupMemberStatus | None,
    ) -> tuple[GroupMember, str]:
        target = await self._members.get(group.id, target_user_id)
        if target is None:
            raise NotAGroupMemberError("That user isn't in this group.")
        if target.role == GroupRole.OWNER:
            raise CannotModifyOwnerError("The group owner's role and status can't be changed.")
        if role is not None:
            if role == GroupRole.OWNER:
                # Ownership transfer is a distinct flow with its own consequences
                # (who may then leave, who is irremovable); V1 doesn't have it.
                raise CannotModifyOwnerError("Ownership transfer isn't supported in V1.")
            await self._members.set_role(target, role)
        if status is not None:
            await self._members.set_status(target, status)

        # Read the name from the user directly rather than the roster: a member who was
        # just removed or demoted-and-removed is no longer in the active roster, and the
        # response still has to name them.
        target_user = await self._users.get_by_id(target_user_id)
        return target, target_user.profile.display_name if target_user else ""

    async def _unique_join_code(self) -> str:
        for _ in range(_JOIN_CODE_ATTEMPTS):
            code = generate_join_code()
            if not await self._groups.join_code_exists(code):
                return code
        raise RuntimeError("Could not generate a unique join code.")

    @staticmethod
    def _require_valid_timezone(timezone: str) -> None:
        if not is_valid_timezone(timezone):
            raise InvalidTimezoneError(
                f"'{timezone}' is not a valid IANA timezone identifier (e.g. 'Asia/Kolkata')."
            )
