"""Challenge and participation endpoints. Thin translation layer only."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import (
    ChallengeEditorContext,
    ChallengeParticipantContext,
    ChallengeServiceDep,
    ChallengeViewer,
    CurrentUser,
    DbSession,
    GroupMemberContext,
    ParticipationServiceDep,
)
from app.domain.challenges.challenge_day import day_index, resolve_challenge_day
from app.domain.challenges.failure_rule import Mode, describe
from app.models.challenge import Challenge, ChallengeParticipant, ChallengeStatus
from app.repositories.challenges import ChallengeParticipantRepository
from app.repositories.groups import GroupRepository
from app.schemas.challenge import (
    ChallengeDetailResponse,
    ChallengeParticipantResponse,
    ChallengeSummaryResponse,
    CreateChallengeRequest,
    DailyProgressResponse,
    UpdateChallengeRequest,
)

challenges_router = APIRouter(prefix="/challenges", tags=["challenges"])
group_challenges_router = APIRouter(prefix="/groups", tags=["challenges"])


def _summary(
    challenge: Challenge,
    *,
    day: int,
    participant_count: int,
    participant: ChallengeParticipant | None,
) -> ChallengeSummaryResponse:
    return ChallengeSummaryResponse(
        id=challenge.id,
        group_id=challenge.group_id,
        name=challenge.name,
        activity_type=challenge.activity_type,
        game_mode=challenge.game_mode,
        status=challenge.status,
        target_value=challenge.target_value,
        unit=challenge.unit,
        day_index=day,
        duration_days=challenge.duration_days,
        participant_count=participant_count,
        my_status=participant.status if participant else None,
    )


def _participant_rows(
    rows: list[tuple[ChallengeParticipant, str]],
) -> list[ChallengeParticipantResponse]:
    # Rank is assigned here, at read time, from the repository's score ordering — it is
    # never persisted (Architecture §3.2).
    return [
        ChallengeParticipantResponse(
            user_id=participant.user_id,
            display_name=display_name,
            status=participant.status,
            outcome=participant.outcome,
            current_score=participant.current_score,
            current_streak=participant.current_streak,
            rank=index,
            joined_at=participant.joined_at,
        )
        for index, (participant, display_name) in enumerate(rows, start=1)
    ]


@group_challenges_router.post(
    "/{group_id}/challenges",
    response_model=ChallengeDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_challenge(
    body: CreateChallengeRequest,
    context: GroupMemberContext,
    challenges: ChallengeServiceDep,
    participation: ParticipationServiceDep,
) -> ChallengeDetailResponse:
    """Any active group member may create a challenge — Architecture §7's flat role
    model has no separate "can create" permission, and API_SPEC gates this on `member`.
    """
    challenge = await challenges.create(
        group=context.group,
        creator_id=context.user.id,
        name=body.name,
        activity_type=body.activity_type,
        target_value=body.target_value,
        unit=body.unit,
        game_mode=body.game_mode,
        verification_method=body.verification_method,
        duration_days=body.duration_days,
        participant_limit=body.participant_limit,
        start_at=body.start_at,
    )
    rows = await participation.list_participants(challenge.id)
    return _detail(
        challenge,
        group_name=context.group.name,
        day=challenges.current_day_index(challenge),
        rows=rows,
        my_user_id=context.user.id,
    )


@group_challenges_router.get(
    "/{group_id}/challenges", response_model=list[ChallengeSummaryResponse]
)
async def list_group_challenges(
    context: GroupMemberContext,
    challenges: ChallengeServiceDep,
    session: DbSession,
) -> list[ChallengeSummaryResponse]:
    participants = ChallengeParticipantRepository(session)
    result: list[ChallengeSummaryResponse] = []
    for challenge in await challenges.list_for_group(context.group.id):
        mine = await participants.get(challenge.id, context.user.id)
        result.append(
            _summary(
                challenge,
                day=challenges.current_day_index(challenge),
                participant_count=await participants.count_active(challenge.id),
                participant=mine,
            )
        )
    return result


@challenges_router.get("", response_model=list[ChallengeSummaryResponse])
async def list_my_challenges(
    current_user: CurrentUser,
    challenges: ChallengeServiceDep,
    session: DbSession,
    challenge_status: Annotated[ChallengeStatus | None, Query(alias="status")] = None,
    group_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ChallengeSummaryResponse]:
    """`scope=mine` is the only scope V1 has — there is no public discovery (ADR 0001),
    so the parameter isn't accepted rather than accepted-and-ignored.
    """
    participants = ChallengeParticipantRepository(session)
    rows = await challenges.list_for_user(
        current_user.id, status=challenge_status, group_id=group_id
    )
    return [
        _summary(
            challenge,
            day=challenges.current_day_index(challenge),
            participant_count=await participants.count_active(challenge.id),
            participant=participant,
        )
        for challenge, participant in rows
    ]


def _detail(
    challenge: Challenge,
    *,
    group_name: str,
    day: int,
    rows: list[tuple[ChallengeParticipant, str]],
    my_user_id: uuid.UUID,
) -> ChallengeDetailResponse:
    mine = next((p for p, _ in rows if p.user_id == my_user_id), None)
    return ChallengeDetailResponse(
        id=challenge.id,
        group_id=challenge.group_id,
        group_name=group_name,
        creator_id=challenge.creator_id,
        name=challenge.name,
        activity_type=challenge.activity_type,
        game_mode=challenge.game_mode,
        verification_method=challenge.verification_method,
        status=challenge.status,
        target_value=challenge.target_value,
        unit=challenge.unit,
        timezone=challenge.timezone,
        start_at=challenge.start_at,
        end_at=challenge.end_at,
        day_index=day,
        duration_days=challenge.duration_days,
        participant_count=len(rows),
        participant_limit=challenge.participant_limit,
        failure_rule=describe(Mode(challenge.game_mode.value)),
        my_status=mine.status if mine else None,
        participants=_participant_rows(rows),
    )


@challenges_router.get("/{challenge_id}", response_model=ChallengeDetailResponse)
async def get_challenge(
    context: ChallengeViewer,
    challenges: ChallengeServiceDep,
    participation: ParticipationServiceDep,
    session: DbSession,
) -> ChallengeDetailResponse:
    group = await GroupRepository(session).get_by_id(context.challenge.group_id)
    rows = await participation.list_participants(context.challenge.id)
    return _detail(
        context.challenge,
        group_name=group.name if group else "",
        day=challenges.current_day_index(context.challenge),
        rows=rows,
        my_user_id=context.user.id,
    )


@challenges_router.patch("/{challenge_id}", response_model=ChallengeDetailResponse)
async def update_challenge(
    body: UpdateChallengeRequest,
    context: ChallengeEditorContext,
    challenges: ChallengeServiceDep,
    participation: ParticipationServiceDep,
    session: DbSession,
) -> ChallengeDetailResponse:
    challenge = await challenges.update_pre_start(
        context.challenge, name=body.name, target_value=body.target_value
    )
    group = await GroupRepository(session).get_by_id(challenge.group_id)
    rows = await participation.list_participants(challenge.id)
    return _detail(
        challenge,
        group_name=group.name if group else "",
        day=challenges.current_day_index(challenge),
        rows=rows,
        my_user_id=context.user.id,
    )


@challenges_router.post("/{challenge_id}/cancel", response_model=ChallengeDetailResponse)
async def cancel_challenge(
    context: ChallengeEditorContext,
    challenges: ChallengeServiceDep,
    participation: ParticipationServiceDep,
    session: DbSession,
) -> ChallengeDetailResponse:
    """The only route to CANCELLED, and only from DRAFT.

    The client requests the *action* "cancel this draft"; the service consults the state
    machine and decides whether that's a legal transition. A running challenge can't be
    cancelled at all, so this can never discard accrued progress.
    """
    challenge = await challenges.cancel(context.challenge)
    group = await GroupRepository(session).get_by_id(challenge.group_id)
    rows = await participation.list_participants(challenge.id)
    return _detail(
        challenge,
        group_name=group.name if group else "",
        day=challenges.current_day_index(challenge),
        rows=rows,
        my_user_id=context.user.id,
    )


@challenges_router.get(
    "/{challenge_id}/participants", response_model=list[ChallengeParticipantResponse]
)
async def list_participants(
    context: ChallengeViewer, participation: ParticipationServiceDep
) -> list[ChallengeParticipantResponse]:
    return _participant_rows(await participation.list_participants(context.challenge.id))


@challenges_router.post(
    "/{challenge_id}/join",
    response_model=ChallengeDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def join_challenge(
    challenge_id: uuid.UUID,
    current_user: CurrentUser,
    challenges: ChallengeServiceDep,
    participation: ParticipationServiceDep,
    session: DbSession,
) -> ChallengeDetailResponse:
    # Not `ChallengeViewer`: joining is exactly the case where the caller has no
    # participant row yet, and group membership is what `ParticipationService.join`
    # checks for itself.
    challenge = await challenges.get(challenge_id)
    await participation.join(challenge=challenge, user_id=current_user.id)
    group = await GroupRepository(session).get_by_id(challenge.group_id)
    rows = await participation.list_participants(challenge.id)
    return _detail(
        challenge,
        group_name=group.name if group else "",
        day=challenges.current_day_index(challenge),
        rows=rows,
        my_user_id=current_user.id,
    )


@challenges_router.post("/{challenge_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_challenge(
    context: ChallengeParticipantContext, participation: ParticipationServiceDep
) -> None:
    assert context.participant is not None  # guaranteed by ChallengeParticipantContext
    await participation.leave(challenge=context.challenge, participant=context.participant)


@challenges_router.get(
    "/{challenge_id}/progress/today", response_model=DailyProgressResponse
)
async def progress_today(
    context: ChallengeParticipantContext, participation: ParticipationServiceDep
) -> DailyProgressResponse:
    assert context.participant is not None
    progress, challenge_day, deadline = await participation.progress_for_today(
        challenge=context.challenge, participant=context.participant
    )
    start_day = resolve_challenge_day(context.challenge.start_at, context.challenge.timezone)
    return DailyProgressResponse(
        challenge_day=challenge_day,
        day_index=day_index(challenge_day, start_day),
        status=progress.status,
        target=context.challenge.target_value,
        unit=context.challenge.unit,
        deadline_at=deadline,
        completed_at=progress.completed_at,
    )


@challenges_router.get(
    "/{challenge_id}/progress/{challenge_day}", response_model=DailyProgressResponse
)
async def progress_for_day(
    challenge_day: date,
    context: ChallengeParticipantContext,
    participation: ParticipationServiceDep,
) -> DailyProgressResponse:
    assert context.participant is not None
    progress, deadline = await participation.progress_for_date(
        challenge=context.challenge, participant=context.participant, day=challenge_day
    )
    start_day = resolve_challenge_day(context.challenge.start_at, context.challenge.timezone)
    return DailyProgressResponse(
        challenge_day=progress.challenge_day,
        day_index=day_index(progress.challenge_day, start_day),
        status=progress.status,
        target=context.challenge.target_value,
        unit=context.challenge.unit,
        deadline_at=deadline,
        completed_at=progress.completed_at,
    )
