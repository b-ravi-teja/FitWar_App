"""Base domain exceptions.

Pure Python — no HTTP status codes, no FastAPI imports (Architecture §12: the domain
layer never knows about HTTP). `core/errors.py` maps these to responses; services and
domain code raise these, never `HTTPException`.
"""


class DomainError(Exception):
    """Base for every domain/service-layer error. `code` is the stable, client-facing identifier."""

    code: str = "DOMAIN_ERROR"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.__class__.__name__
        super().__init__(self.detail)


class NotFoundError(DomainError):
    code = "NOT_FOUND"


class ConflictError(DomainError):
    code = "CONFLICT"


class ForbiddenError(DomainError):
    code = "FORBIDDEN"


class RateLimitedError(DomainError):
    code = "RATE_LIMITED"

    def __init__(
        self, detail: str | None = None, *, retry_after_seconds: int | None = None
    ) -> None:
        # Seconds until the caller may retry. A plain duration, not an HTTP concept —
        # `core/errors.py` is what turns it into a Retry-After header.
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail)
