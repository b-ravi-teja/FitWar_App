"""Current-user profile endpoints. Thin translation layer only."""

from fastapi import APIRouter

from app.core.deps import CurrentUser, UserServiceDep
from app.models.user import User
from app.schemas.user import UpdateProfileRequest, UserResponse

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
