from app.domain.common.exceptions import ConflictError, ForbiddenError, NotFoundError


class ChallengeNotFoundError(NotFoundError):
    code = "CHALLENGE_NOT_FOUND"


class NotAParticipantError(ForbiddenError):
    code = "NOT_A_PARTICIPANT"


class ChallengeNotActiveError(ConflictError):
    code = "CHALLENGE_NOT_ACTIVE"


class ChallengeAlreadyActiveError(ConflictError):
    """Edit attempted after start. `PATCH /challenges/{id}` is pre-start only."""

    code = "CHALLENGE_ALREADY_ACTIVE"


class ChallengeAlreadyEndedError(ConflictError):
    code = "CHALLENGE_ALREADY_ENDED"


class AlreadyJoinedError(ConflictError):
    code = "ALREADY_JOINED"


class ParticipantLimitReachedError(ConflictError):
    code = "PARTICIPANT_LIMIT_REACHED"


class CannotRejoinError(ConflictError):
    """A participant who left or was eliminated cannot re-enter the same challenge.

    Participant statuses are terminal by design (Architecture §3.3) — re-entering would
    mean reviving a terminal state, and for SURVIVAL it would make elimination
    meaningless. Rejoining a future challenge is always available.
    """

    code = "CANNOT_REJOIN"


class InvalidDayError(NotFoundError):
    """A progress date outside the challenge's own day range."""

    code = "DAY_OUT_OF_RANGE"


class InvalidChallengeConfigError(ConflictError):
    code = "INVALID_CHALLENGE_CONFIG"
