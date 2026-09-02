from app.domain.common.exceptions import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
)


class GroupNotFoundError(NotFoundError):
    code = "GROUP_NOT_FOUND"


class InvalidJoinCodeError(NotFoundError):
    code = "INVALID_CODE"


class NotAGroupMemberError(ForbiddenError):
    code = "NOT_A_MEMBER"


class NotAGroupAdminError(ForbiddenError):
    code = "FORBIDDEN"


class AlreadyGroupMemberError(ConflictError):
    code = "ALREADY_MEMBER"


class MemberRemovedError(ForbiddenError):
    """A removed member presented a valid invite code.

    Removal is an admin moderation decision; an invite code must not be a way around it.
    Rejoining requires an admin to reinstate the membership via
    `PATCH /groups/{id}/members/{user_id}`.
    """

    code = "MEMBER_REMOVED"


class OwnerCannotLeaveError(ConflictError):
    """Leaving would strand the group without an owner.

    V1 has no ownership-transfer flow, so the owner leaving is refused outright rather
    than silently promoting an arbitrary admin.
    """

    code = "OWNER_CANNOT_LEAVE"


class CannotModifyOwnerError(ForbiddenError):
    """An admin tried to demote or remove the owner, or the owner tried it on themselves."""

    code = "CANNOT_MODIFY_OWNER"


class InvalidTimezoneError(DomainError):
    code = "INVALID_TIMEZONE"
