"""1v1 battle endpoints. Thin translation layer only — every decision is in the service.

Authorization is a dependency, not a line in each handler: `BattleParticipantContext`
loads the battle *and* the caller's participation in one place, and answers
`BATTLE_NOT_FOUND` when they have none, so no route can forget the check and none can
be used to discover that someone else's battle exists (§12).
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.deps import BattleParticipant, BattleServiceDep, CurrentUser, GroupMemberContext
from app.domain.verification.evidence import HealthEvidence
from app.models.battle import BattleStatus
from app.schemas.battle import (
    BattleResponse,
    BattleSideResponse,
    CreateBattleRequest,
    RivalResponse,
    SubmitBattleEvidenceResponse,
)
from app.schemas.game import DayResolutionResponse
from app.schemas.verification import (
    SubmitVerificationRequest,
    SubmitVerificationResponse,
    VerificationRecordResponse,
)
from app.services.battle_service import BattleView

router = APIRouter(prefix="/battles", tags=["battles"])


def _response(view: BattleView, *, now: datetime | None = None) -> BattleResponse:
    now = now or datetime.now(UTC)
    remaining = int((view.battle.end_at - now).total_seconds())
    return BattleResponse(
        id=view.battle.id,
        group_id=view.battle.group_id,
        status=view.battle.status,
        activity_type=view.challenge.activity_type,
        target_value=view.challenge.target_value,
        unit=view.challenge.unit,
        day_index=view.day_index,
        duration_days=view.challenge.duration_days,
        timezone=view.battle.timezone,
        start_at=view.battle.start_at,
        end_at=view.battle.end_at,
        completed_at=view.battle.completed_at,
        time_remaining_seconds=max(0, remaining),
        sides=[
            BattleSideResponse(
                user_id=side.user_id,
                display_name=side.display_name,
                status=side.status,
                score=side.score,
                days_completed=side.days_completed,
                is_me=side.is_me,
            )
            for side in view.sides
        ],
        winner_user_id=view.winner_user_id,
        my_outcome=view.my_outcome.value if view.my_outcome else None,
        my_xp_awarded=view.my_xp_awarded,
    )


@router.get("", response_model=list[BattleResponse])
async def list_battles(
    current_user: CurrentUser,
    battles: BattleServiceDep,
    battle_status: Annotated[BattleStatus | None, Query(alias="status")] = None,
) -> list[BattleResponse]:
    """The caller's battles — live, pending and historical.

    `scope=mine` is the only scope there is, so it isn't a parameter: a battle you are
    not in is not listed, filtered or hidden, it simply is not selected.
    """
    return [_response(view) for view in await battles.list_for_user(
        current_user.id, status=battle_status
    )]


@router.get("/rivals", response_model=list[RivalResponse])
async def list_rivals(
    context: GroupMemberContext,
    battles: BattleServiceDep,
    group_id: Annotated[uuid.UUID, Query()],
) -> list[RivalResponse]:
    """Squad-mates the caller can challenge, with the head-to-head record.

    `GroupMemberContext` resolves `group_id` from the query string and 403s a
    non-member, so this can't be used to enumerate a squad the caller isn't in.
    """
    return [
        RivalResponse(
            user_id=user_id,
            display_name=display_name,
            wins_against=wins,
            losses_against=losses,
            live_battle_id=live_battle_id,
        )
        for user_id, display_name, wins, losses, live_battle_id in await battles.rivals(
            context.group.id, context.user.id
        )
    ]


@router.post("", response_model=BattleResponse, status_code=status.HTTP_201_CREATED)
async def create_battle(
    body: CreateBattleRequest,
    current_user: CurrentUser,
    battles: BattleServiceDep,
) -> BattleResponse:
    """Challenge one squad-mate. The battle waits at `pending` until they accept."""
    battle = await battles.create(
        creator_id=current_user.id,
        opponent_user_id=body.opponent_user_id,
        activity_type=body.activity_type,
        target_value=body.target_value,
        duration_days=body.duration_days,
        group_id=body.group_id,
    )
    return _response(await battles.view(battle, current_user.id))


@router.get("/{battle_id}", response_model=BattleResponse)
async def get_battle(context: BattleParticipant, battles: BattleServiceDep) -> BattleResponse:
    return _response(await battles.view(context.battle, context.user.id))


@router.post("/{battle_id}/accept", response_model=BattleResponse)
async def accept_battle(
    context: BattleParticipant, battles: BattleServiceDep
) -> BattleResponse:
    """Accept an invitation. Idempotent — accepting twice returns the same battle."""
    battle = await battles.accept(context.battle.id, context.user.id)
    return _response(await battles.view(battle, context.user.id))


@router.post("/{battle_id}/decline", response_model=BattleResponse)
async def decline_battle(
    context: BattleParticipant, battles: BattleServiceDep
) -> BattleResponse:
    """Decline an invitation. The battle is cancelled and no result is recorded."""
    battle = await battles.decline(context.battle.id, context.user.id)
    return _response(await battles.view(battle, context.user.id))


@router.post("/{battle_id}/verify", response_model=SubmitBattleEvidenceResponse)
async def submit_battle_evidence(
    body: SubmitVerificationRequest,
    context: BattleParticipant,
    battles: BattleServiceDep,
) -> SubmitBattleEvidenceResponse:
    """Submit today's evidence for the caller's own side.

    Identical request shape to `POST /challenges/{id}/verify`, because it is the same
    verification path — this handler adds no evidence handling of its own. The side the
    evidence lands on comes from the authenticated user, never from the body, so there
    is no way to submit on an opponent's behalf.
    """
    evidence = body.evidence
    outcome, view = await battles.submit_evidence(
        battle=context.battle,
        user_id=context.user.id,
        provider_name=body.provider,
        evidence=HealthEvidence(
            metric=evidence.metric,
            value=evidence.value,
            unit=evidence.unit,
            period_start=evidence.period_start,
            period_end=evidence.period_end,
            source_name=evidence.source_name,
            source_bundle_id=evidence.source_bundle_id,
            was_user_entered=evidence.was_user_entered,
        ),
        raw_payload=body.model_dump(mode="json"),
    )
    return SubmitBattleEvidenceResponse(
        verification=SubmitVerificationResponse(
            verification=VerificationRecordResponse.model_validate(
                outcome.record, from_attributes=True
            ),
            challenge_day=outcome.challenge_day,
            day_status=outcome.progress.status,
            deadline_at=outcome.deadline_at,
            idempotent_replay=outcome.idempotent_replay,
            resolution=(
                DayResolutionResponse(
                    xp_awarded=outcome.resolution.xp_awarded,
                    completion_xp=outcome.resolution.completion_xp,
                    streak_bonus_xp=outcome.resolution.streak_bonus_xp,
                    score_delta=outcome.resolution.score_delta,
                    current_streak=outcome.resolution.current_streak,
                )
                if outcome.resolution is not None
                else None
            ),
        ),
        battle=_response(view),
    )
