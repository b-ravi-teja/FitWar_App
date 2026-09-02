from app.domain.common.exceptions import ConflictError, DomainError, ForbiddenError, NotFoundError


class EmailAlreadyTakenError(ConflictError):
    code = "EMAIL_TAKEN"


class InvalidCredentialsError(DomainError):
    code = "INVALID_CREDENTIALS"


class AccountDeletedError(ForbiddenError):
    code = "ACCOUNT_DELETED"


class RefreshTokenInvalidError(DomainError):
    code = "REFRESH_INVALID"


class RefreshTokenReuseDetectedError(DomainError):
    """A revoked refresh token was presented again.

    The whole token family is revoked in response (Architecture §6).
    """

    code = "REFRESH_REUSE_DETECTED"


class UserNotFoundError(NotFoundError):
    code = "USER_NOT_FOUND"


class UnauthenticatedError(DomainError):
    """Missing/malformed/expired access token, or its user no longer exists or is inactive."""

    code = "UNAUTHENTICATED"


class ResetTokenInvalidError(DomainError):
    code = "RESET_TOKEN_INVALID_OR_EXPIRED"
