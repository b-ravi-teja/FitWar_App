"""Group endpoints. Thin translation layer — every rule lives in `GroupService`."""

import uuid

from fastapi import APIRouter, status

from app.core.deps import (
    CurrentUser,
    DbSession,
    GroupAdminContext,
    GroupMemberContext,
    GroupServiceDep,
)
from app.models.group import Group, GroupRole
from app.repositories.challenges import (
    ChallengeParticipantRepository,
    GroupActivityRepository,
)
from app.schemas.group import (
    CreateGroupRequest,
    GroupActivityEntry,
    GroupMemberResponse,
    GroupResponse,
    GroupSummaryResponse,
    JoinGroupRequest,
    UpdateGroupMemberRequest,
    UpdateGroupRequest,
)

router = APIRouter(prefix="/groups", tags=["groups"])

ACTIVITY_LIMIT = 20


def _to_detail(
    group: Group, *, member_count: int, active_challenge_count: int, my_role: GroupRole
) -> GroupResponse:
    return GroupResponse(
        id=group.id,
        name=group.name,
        timezone=group.timezone,
        privacy=group.privacy.value,
        owner_id=group.owner_id,
        member_count=member_count,
        active_challenge_count=active_challenge_count,
        created_at=group.created_at,
        join_code=group.join_code,
        my_role=my_role,
    )


@router.get("", response_model=list[GroupSummaryResponse])
async def list_groups(
    current_user: CurrentUser, groups: GroupServiceDep
) -> list[GroupSummaryResponse]:
    rows = await groups.list_for_user(current_user.id)
    return [
        GroupSummaryResponse(
            id=group.id,
            name=group.name,
            timezone=group.timezone,
            member_count=member_count,
            active_challenge_count=challenge_count,
        )
        for group, member_count, challenge_count in rows
    ]


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: CreateGroupRequest, current_user: CurrentUser, groups: GroupServiceDep
) -> GroupResponse:
    group = await groups.create(
        owner_id=current_user.id, name=body.name, timezone=body.timezone
    )
    members, challenges = await groups.counts_for(group.id)
    return _to_detail(
        group, member_count=members, active_challenge_count=challenges, my_role=GroupRole.OWNER
    )


@router.post("/join", response_model=GroupResponse)
async def join_group_by_code(
    body: JoinGroupRequest, current_user: CurrentUser, groups: GroupServiceDep
) -> GroupResponse:
    """Join with only a code — what the design's JOIN CODE card supports.

    `POST /groups/{id}/join` below is the API_SPEC route and backs invite *links*, which
    carry the group id. This one backs typing `K7-XR9` into the app, where the group id
    isn't known yet. Both delegate to the same service call.
    """
    member = await groups.join_by_code(user_id=current_user.id, join_code=body.join_code)
    group = await groups.get_for_member(member.group_id, current_user.id)
    members, challenges = await groups.counts_for(group.id)
    return _to_detail(
        group,
        member_count=members,
        active_challenge_count=challenges,
        my_role=member.role,
    )


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(context: GroupMemberContext, groups: GroupServiceDep) -> GroupResponse:
    members, challenges = await groups.counts_for(context.group.id)
    return _to_detail(
        context.group,
        member_count=members,
        active_challenge_count=challenges,
        my_role=context.member.role,
    )


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    body: UpdateGroupRequest, context: GroupAdminContext, groups: GroupServiceDep
) -> GroupResponse:
    group = await groups.update(context.group, name=body.name, timezone=body.timezone)
    members, challenges = await groups.counts_for(group.id)
    return _to_detail(
        group,
        member_count=members,
        active_challenge_count=challenges,
        my_role=context.member.role,
    )


@router.post("/{group_id}/join", response_model=GroupResponse)
async def join_group(
    group_id: uuid.UUID,
    body: JoinGroupRequest,
    current_user: CurrentUser,
    groups: GroupServiceDep,
) -> GroupResponse:
    member = await groups.join_by_code(
        user_id=current_user.id, join_code=body.join_code, group_id=group_id
    )
    group = await groups.get_for_member(group_id, current_user.id)
    members, challenges = await groups.counts_for(group.id)
    return _to_detail(
        group,
        member_count=members,
        active_challenge_count=challenges,
        my_role=member.role,
    )


@router.post("/{group_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_group(context: GroupMemberContext, groups: GroupServiceDep) -> None:
    await groups.leave(group=context.group, member=context.member)


@router.get("/{group_id}/members", response_model=list[GroupMemberResponse])
async def list_members(
    context: GroupMemberContext, groups: GroupServiceDep, session: DbSession
) -> list[GroupMemberResponse]:
    participants = ChallengeParticipantRepository(session)
    roster = await groups.roster(context.group.id)
    result: list[GroupMemberResponse] = []
    for member, display_name in roster:
        active_ids = await participants.active_challenge_ids_for_group_member(
            context.group.id, member.user_id
        )
        result.append(
            GroupMemberResponse(
                user_id=member.user_id,
                display_name=display_name,
                role=member.role,
                status=member.status,
                joined_at=member.joined_at,
                active_challenge_count=len(active_ids),
            )
        )
    return result


@router.patch("/{group_id}/members/{user_id}", response_model=GroupMemberResponse)
async def update_member(
    user_id: uuid.UUID,
    body: UpdateGroupMemberRequest,
    context: GroupAdminContext,
    groups: GroupServiceDep,
    session: DbSession,
) -> GroupMemberResponse:
    member, display_name = await groups.update_member(
        group=context.group,
        actor=context.member,
        target_user_id=user_id,
        role=body.role,
        status=body.status,
    )
    active_ids = await ChallengeParticipantRepository(
        session
    ).active_challenge_ids_for_group_member(context.group.id, user_id)
    return GroupMemberResponse(
        user_id=member.user_id,
        display_name=display_name,
        role=member.role,
        status=member.status,
        joined_at=member.joined_at,
        active_challenge_count=len(active_ids),
    )


@router.get("/{group_id}/activity", response_model=list[GroupActivityEntry])
async def group_activity(
    context: GroupMemberContext, session: DbSession
) -> list[GroupActivityEntry]:
    """The Feed tab.

    Derived from what Phase 3 actually records — who joined, and which challenges were
    started. Proof shares and competitive events (the design's other feed content) need
    the Media and XP phases; they're absent here rather than mocked.
    """
    activity = GroupActivityRepository(session)
    entries: list[GroupActivityEntry] = []

    for display_name, joined_at in await activity.joins(context.group.id, ACTIVITY_LIMIT):
        entries.append(
            GroupActivityEntry(
                kind="member_joined",
                actor_display_name=display_name,
                text="joined the squad",
                occurred_at=joined_at,
            )
        )
    for display_name, name, created_at in await activity.challenge_creations(
        context.group.id, ACTIVITY_LIMIT
    ):
        entries.append(
            GroupActivityEntry(
                kind="challenge_created",
                actor_display_name=display_name,
                text=f"started {name}",
                occurred_at=created_at,
            )
        )

    entries.sort(key=lambda e: e.occurred_at, reverse=True)
    return entries[:ACTIVITY_LIMIT]
