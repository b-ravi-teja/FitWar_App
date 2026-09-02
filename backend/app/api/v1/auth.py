"""Auth endpoints. Thin translation layer only — all logic lives in AuthService."""

from fastapi import APIRouter, status

from app.core.deps import AuthServiceDep
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequestRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, auth_service: AuthServiceDep) -> RegisterResponse:
    user, tokens = await auth_service.register(
        email=body.email, password=body.password, display_name=body.display_name
    )
    return RegisterResponse(user_id=user.id, **vars(tokens))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, auth_service: AuthServiceDep) -> TokenResponse:
    _, tokens = await auth_service.login(email=body.email, password=body.password)
    return TokenResponse(**vars(tokens))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, auth_service: AuthServiceDep) -> TokenResponse:
    tokens = await auth_service.refresh(raw_refresh_token=body.refresh_token)
    return TokenResponse(**vars(tokens))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, auth_service: AuthServiceDep) -> None:
    await auth_service.logout(raw_refresh_token=body.refresh_token)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    body: PasswordResetRequestRequest, auth_service: AuthServiceDep
) -> None:
    # Always 202, regardless of whether the email exists (ADR 0007) — never a signal
    # for account enumeration.
    await auth_service.request_password_reset(email=body.email)


@router.post("/password-reset/confirm", status_code=status.HTTP_200_OK)
async def confirm_password_reset(
    body: PasswordResetConfirmRequest, auth_service: AuthServiceDep
) -> None:
    await auth_service.confirm_password_reset(token=body.token, new_password=body.new_password)
