"""Auth endpoints. Thin translation layer only — all logic lives in AuthService.

Rate limits are declared here as route dependencies rather than implemented in the
handlers: an endpoint's throttling is visible at its definition, and the enforcement
lives entirely in `core/rate_limit.py` (Architecture §7).
"""

from fastapi import APIRouter, Depends, status

from app.core.deps import AuthServiceDep
from app.core.rate_limit import (
    RATE_LIMITED_RESPONSE,
    IdentitySource,
    RateLimitGuard,
    RuleName,
)
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

# Login and password-reset carry two buckets each. The per-IP one stops one source
# spraying many accounts; the per-account one stops many sources converging on a single
# account, which a per-IP limit alone cannot see. The account bucket counts whatever
# email was submitted, existing or not, and both buckets return the identical 429 body,
# so nothing here can be used to probe which addresses are registered.
_login_limit = RateLimitGuard(
    (RuleName.AUTH_LOGIN_IP, IdentitySource.IP),
    (RuleName.AUTH_LOGIN_ACCOUNT, IdentitySource.ACCOUNT_EMAIL),
)
_register_limit = RateLimitGuard((RuleName.AUTH_REGISTER_IP, IdentitySource.IP))
_refresh_limit = RateLimitGuard((RuleName.AUTH_REFRESH_IP, IdentitySource.IP))
_password_reset_limit = RateLimitGuard(
    (RuleName.AUTH_PASSWORD_RESET_IP, IdentitySource.IP),
    (RuleName.AUTH_PASSWORD_RESET_ACCOUNT, IdentitySource.ACCOUNT_EMAIL),
)


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_register_limit)],
    responses=RATE_LIMITED_RESPONSE,
)
async def register(body: RegisterRequest, auth_service: AuthServiceDep) -> RegisterResponse:
    user, tokens = await auth_service.register(
        email=body.email, password=body.password, display_name=body.display_name
    )
    return RegisterResponse(user_id=user.id, **vars(tokens))


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(_login_limit)],
    responses=RATE_LIMITED_RESPONSE,
)
async def login(body: LoginRequest, auth_service: AuthServiceDep) -> TokenResponse:
    _, tokens = await auth_service.login(email=body.email, password=body.password)
    return TokenResponse(**vars(tokens))


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(_refresh_limit)],
    responses=RATE_LIMITED_RESPONSE,
)
async def refresh(body: RefreshRequest, auth_service: AuthServiceDep) -> TokenResponse:
    tokens = await auth_service.refresh(raw_refresh_token=body.refresh_token)
    return TokenResponse(**vars(tokens))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(body: LogoutRequest, auth_service: AuthServiceDep) -> None:
    await auth_service.logout(raw_refresh_token=body.refresh_token)


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_password_reset_limit)],
    responses=RATE_LIMITED_RESPONSE,
)
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
