"""Shared FastAPI dependencies: DB session passthrough, current-user auth, service factories."""

import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import InvalidTokenError, decode_access_token
from app.domain.auth.exceptions import UnauthenticatedError
from app.models.user import User, UserStatus
from app.repositories.users import UserRepository
from app.services.auth_service import AuthService

_bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]
BearerCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]


async def current_user(
    request: Request, credentials: BearerCredentials, session: DbSession
) -> User:
    if credentials is None:
        raise UnauthenticatedError("Missing bearer token.")

    try:
        subject = decode_access_token(credentials.credentials)
    except InvalidTokenError as exc:
        raise UnauthenticatedError(str(exc)) from exc

    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise UnauthenticatedError("Malformed subject claim.") from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None or user.status != UserStatus.ACTIVE:
        raise UnauthenticatedError("User not found or inactive.")

    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def get_auth_service(session: DbSession) -> AuthService:
    return AuthService(session)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
