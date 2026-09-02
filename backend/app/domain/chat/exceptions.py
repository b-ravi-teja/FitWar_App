"""Chat domain errors. Pure — no HTTP status codes (Architecture §12)."""

from app.domain.common.exceptions import DomainError, NotFoundError


class ReactionNotAllowedError(DomainError):
    """V1 ships a fixed emoji set, not an open field (§18)."""

    code = "REACTION_NOT_ALLOWED"


class MessageNotFoundError(NotFoundError):
    """Also returned for a message in another group — an identical 404, so a member of
    one group cannot use reactions to probe another group's message ids."""

    code = "MESSAGE_NOT_FOUND"
