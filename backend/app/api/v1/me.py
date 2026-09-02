"""Current-user profile and health-connection endpoints. Thin translation layer only."""

import uuid

from fastapi import APIRouter, status

from app.core.deps import CurrentUser, DbSession, HealthConnectionServiceDep, UserServiceDep
from app.models.user import User
from app.models.verification import HealthConnection
from app.repositories.game import GameRepository
from app.schemas.game import XPSummaryResponse, XPTransactionResponse
from app.schemas.user import UpdateProfileRequest, UserResponse
from app.schemas.verification import (
    CreateHealthConnectionRequest,
    HealthConnectionResponse,
)
from app.services.game_service import xp_summary

router = APIRouter(prefix="/me", tags=["me"])


def _to_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        email=user.email,
        display_name=user.profile.display_name,
        avatar_media_id=user.profile.avatar_media_id,
        xp_total=user.profile.xp_total,
        notification_preferences=user.profile.notification_preferences,
    )


def _connection(connection: HealthConnection) -> HealthConnectionResponse:
    return HealthConnectionResponse(
        id=connection.id,
        provider=connection.provider,
        status=connection.status,
        last_synced_at=connection.last_synced_at,
        connected_at=connection.created_at,
    )


@router.get("", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> UserResponse:
    return _to_response(current_user)


@router.patch("", response_model=UserResponse)
async def patch_me(
    body: UpdateProfileRequest, current_user: CurrentUser, user_service: UserServiceDep
) -> UserResponse:
    updated = await user_service.update_profile(
        current_user,
        display_name=body.display_name,
        notification_preferences=body.notification_preferences,
    )
    return _to_response(updated)


@router.get("/health-connections", response_model=list[HealthConnectionResponse])
async def list_health_connections(
    current_user: CurrentUser, connections: HealthConnectionServiceDep
) -> list[HealthConnectionResponse]:
    return [_connection(c) for c in await connections.list_for_user(current_user.id)]


@router.post(
    "/health-connections",
    response_model=HealthConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_health_connection(
    body: CreateHealthConnectionRequest,
    current_user: CurrentUser,
    connections: HealthConnectionServiceDep,
) -> HealthConnectionResponse:
    """Record that the user linked a health source.

    Idempotent: connecting an already-linked provider revives it rather than failing,
    which is what the client needs when a user re-grants permission in iOS Settings.
    """
    connection = await connections.connect(user_id=current_user.id, provider=body.provider)
    return _connection(connection)


@router.delete("/health-connections/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_health_connection(
    connection_id: uuid.UUID,
    current_user: CurrentUser,
    connections: HealthConnectionServiceDep,
) -> None:
    await connections.revoke(user_id=current_user.id, connection_id=connection_id)


@router.get("/xp", response_model=XPSummaryResponse)
async def get_my_xp(current_user: CurrentUser, session: DbSession) -> XPSummaryResponse:
    """XP total, server-computed level, and the recent ledger.

    The ledger is the source of truth and `xp_total` its cached projection
    (Architecture §3.2); both come from the server so the client never derives a level.
    """
    total, level, into_level, to_next = await xp_summary(session, current_user.id)
    transactions = await GameRepository(session).xp_history(current_user.id, limit=50)
    return XPSummaryResponse(
        xp_total=total,
        level=level,
        xp_into_level=into_level,
        xp_to_next_level=to_next,
        transactions=[
            XPTransactionResponse(
                id=t.id, amount=t.amount, reason=t.reason, created_at=t.created_at
            )
            for t in transactions
        ],
    )
