"""Shared FastAPI dependencies: DB session passthrough, current-user auth, service factories."""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import InvalidTokenError, decode_access_token
from app.domain.auth.exceptions import UnauthenticatedError
from app.domain.challenges.exceptions import NotAParticipantError
from app.domain.groups.exceptions import (
    GroupNotFoundError,
    NotAGroupAdminError,
    NotAGroupMemberError,
)
from app.domain.verification.exceptions import NotAReviewerError
from app.models.challenge import Challenge, ChallengeParticipant
from app.models.group import Group, GroupMember, GroupRole
from app.models.user import User, UserStatus
from app.repositories.groups import GroupMemberRepository, GroupRepository
from app.repositories.users import UserRepository
from app.services.auth_service import AuthService
from app.services.challenge_service import ChallengeService
from app.services.chat_service import ChatService
from app.services.game_service import GameService
from app.services.group_service import GroupService
from app.services.health_connection_service import HealthConnectionService
from app.services.media_service import MediaService
from app.services.participation_service import ParticipationService
from app.services.proof_review_service import ProofReviewService
from app.services.user_service import UserService
from app.services.verification_service import VerificationService

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


def get_user_service(session: DbSession) -> UserService:
    return UserService(session)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


def get_group_service(session: DbSession) -> GroupService:
    return GroupService(session)


GroupServiceDep = Annotated[GroupService, Depends(get_group_service)]


def get_challenge_service(session: DbSession) -> ChallengeService:
    return ChallengeService(session)


ChallengeServiceDep = Annotated[ChallengeService, Depends(get_challenge_service)]


def get_participation_service(session: DbSession) -> ParticipationService:
    return ParticipationService(session)


ParticipationServiceDep = Annotated[ParticipationService, Depends(get_participation_service)]


def get_verification_service(session: DbSession) -> VerificationService:
    return VerificationService(session)


VerificationServiceDep = Annotated[VerificationService, Depends(get_verification_service)]


def get_game_service(session: DbSession) -> GameService:
    return GameService(session)


GameServiceDep = Annotated[GameService, Depends(get_game_service)]


def get_media_service(session: DbSession) -> MediaService:
    return MediaService(session)


MediaServiceDep = Annotated[MediaService, Depends(get_media_service)]


def get_proof_review_service(session: DbSession) -> ProofReviewService:
    return ProofReviewService(session)


ProofReviewServiceDep = Annotated[ProofReviewService, Depends(get_proof_review_service)]


def get_chat_service(session: DbSession) -> ChatService:
    return ChatService(session)


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


def get_health_connection_service(session: DbSession) -> HealthConnectionService:
    return HealthConnectionService(session)


HealthConnectionServiceDep = Annotated[
    HealthConnectionService, Depends(get_health_connection_service)
]


# ---------------------------------------------------------------------------
# Authorization dependencies (Architecture §7).
#
# "Never trust a client-supplied ID without an authorization check that hits the
# database." Each of these loads the resource *and* the caller's relationship to it in
# one place, so no route re-implements the check and none can forget it.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupContext:
    group: Group
    member: GroupMember
    user: User

    @property
    def is_admin(self) -> bool:
        return self.member.role in (GroupRole.OWNER, GroupRole.ADMIN)


async def group_context(
    group_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> GroupContext:
    """403 unless the caller is an *active* member of an existing group.

    Returns their `GroupMember` alongside the group so downstream role checks are free.
    """
    group = await GroupRepository(session).get_by_id(group_id)
    if group is None:
        raise GroupNotFoundError(f"No group {group_id}.")
    member = await GroupMemberRepository(session).get_active(group_id, user.id)
    if member is None:
        raise NotAGroupMemberError("Only active members can access this group.")
    return GroupContext(group=group, member=member, user=user)


GroupMemberContext = Annotated[GroupContext, Depends(group_context)]


async def group_admin_context(context: GroupMemberContext) -> GroupContext:
    """Layers on `group_context` — 403 unless the caller is owner or admin."""
    if not context.is_admin:
        raise NotAGroupAdminError("Only the group's owner or an admin can do that.")
    return context


GroupAdminContext = Annotated[GroupContext, Depends(group_admin_context)]


@dataclass(frozen=True)
class ChallengeContext:
    challenge: Challenge
    participant: ChallengeParticipant | None
    user: User


async def challenge_viewer_context(
    challenge_id: uuid.UUID,
    user: CurrentUser,
    challenge_service: ChallengeServiceDep,
) -> ChallengeContext:
    """Readable by a participant, or by any active member of the challenge's group."""
    challenge, participant = await challenge_service.get_for_viewer(challenge_id, user.id)
    return ChallengeContext(challenge=challenge, participant=participant, user=user)


ChallengeViewer = Annotated[ChallengeContext, Depends(challenge_viewer_context)]


async def challenge_participant_context(context: ChallengeViewer) -> ChallengeContext:
    """403 unless the caller actually holds a `ChallengeParticipant` row."""
    if context.participant is None:
        raise NotAParticipantError("You haven't joined this challenge.")
    return context


ChallengeParticipantContext = Annotated[ChallengeContext, Depends(challenge_participant_context)]


async def challenge_reviewer_context(
    context: ChallengeViewer, session: DbSession
) -> ChallengeContext:
    """403 unless the caller may review this challenge's manual proof (§7, §20.5).

    The reviewer set is the challenge's creator plus the group's owner/admins — the same
    flat role model everything else uses, with no new permission concept. Note this only
    establishes *who may review this challenge*; refusing self-review is a separate rule
    enforced per-proof in `ProofReviewService`, because a creator reviewing their own
    submission is authorized here and still forbidden there.
    """
    if context.challenge.creator_id == context.user.id:
        return context
    member = await GroupMemberRepository(session).get_active(
        context.challenge.group_id, context.user.id
    )
    if member is None or member.role not in (GroupRole.OWNER, GroupRole.ADMIN):
        raise NotAReviewerError("You aren't a reviewer for this challenge.")
    return context


ChallengeReviewerContext = Annotated[ChallengeContext, Depends(challenge_reviewer_context)]


async def challenge_editor_context(
    context: ChallengeViewer, session: DbSession
) -> ChallengeContext:
    """403 unless the caller created the challenge or administers its group.

    This is exactly Architecture §7's flat role model — "creator can edit pre-start,
    admin can moderate" — and no new permission concept beyond it.
    """
    if context.challenge.creator_id == context.user.id:
        return context
    member = await GroupMemberRepository(session).get_active(
        context.challenge.group_id, context.user.id
    )
    if member is None or member.role not in (GroupRole.OWNER, GroupRole.ADMIN):
        raise NotAGroupAdminError("Only the creator or a group admin can change this challenge.")
    return context


ChallengeEditorContext = Annotated[ChallengeContext, Depends(challenge_editor_context)]
