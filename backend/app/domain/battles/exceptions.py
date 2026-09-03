from app.domain.common.exceptions import ConflictError, ForbiddenError, NotFoundError


class BattleNotFoundError(NotFoundError):
    """Also raised for a battle the caller may not see.

    Deliberately identical to "no such battle": §12 forbids leaking the existence of a
    private battle, and object ids are not treated as secrets.
    """

    code = "BATTLE_NOT_FOUND"


class NotABattleParticipantError(ForbiddenError):
    code = "NOT_A_BATTLE_PARTICIPANT"


class OpponentNotAvailableError(ForbiddenError):
    """One error for "no such user", "that's you", and "you share no group".

    Collapsing them keeps `POST /battles` from becoming an account-existence oracle.
    """

    code = "OPPONENT_NOT_AVAILABLE"


class GroupRequiredError(ConflictError):
    """Two users who share several groups must say which one hosts the battle."""

    code = "GROUP_REQUIRED"


class AlreadyPendingWithUserError(ConflictError):
    """A live (pending or active) battle already exists between these two users."""

    code = "ALREADY_PENDING_WITH_USER"


class NotInvitedError(ConflictError):
    code = "NOT_INVITED"


class BattleNotActiveError(ConflictError):
    code = "BATTLE_NOT_ACTIVE"


class BattleNotPendingError(ConflictError):
    code = "BATTLE_NOT_PENDING"


class BattleAlreadyFinalizedError(ConflictError):
    """A completed battle's result is written once and never revised (§8, §21)."""

    code = "BATTLE_ALREADY_FINALIZED"


class InvalidBattleConfigError(ConflictError):
    code = "INVALID_BATTLE_CONFIG"
