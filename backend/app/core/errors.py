"""Centralized mapping from domain exceptions to the one Problem Details response shape.

This is the only place in the app that translates an exception into an HTTP response.
No route handler or service should ever construct an error JSON body by hand.
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger
from app.domain.auth.exceptions import (
    AccountDeletedError,
    EmailAlreadyTakenError,
    InvalidCredentialsError,
    RefreshTokenInvalidError,
    RefreshTokenReuseDetectedError,
    UnauthenticatedError,
    UserNotFoundError,
)
from app.domain.common.exceptions import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
)
from app.schemas.common import ProblemDetail

logger = get_logger(__name__)

# Explicit status per exception type. Looked up by walking the MRO, so a future
# subclass not listed here still inherits a sensible status from its base class.
_STATUS_MAP: dict[type[DomainError], int] = {
    DomainError: status.HTTP_400_BAD_REQUEST,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    ForbiddenError: status.HTTP_403_FORBIDDEN,
    RateLimitedError: status.HTTP_429_TOO_MANY_REQUESTS,
    EmailAlreadyTakenError: status.HTTP_409_CONFLICT,
    InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,
    AccountDeletedError: status.HTTP_403_FORBIDDEN,
    RefreshTokenInvalidError: status.HTTP_401_UNAUTHORIZED,
    RefreshTokenReuseDetectedError: status.HTTP_401_UNAUTHORIZED,
    UserNotFoundError: status.HTTP_404_NOT_FOUND,
    UnauthenticatedError: status.HTTP_401_UNAUTHORIZED,
}


def _resolve_status(exc: DomainError) -> int:
    for cls in type(exc).__mro__:
        if cls in _STATUS_MAP:
            return _STATUS_MAP[cls]
    return status.HTTP_400_BAD_REQUEST


def _title_from_code(code: str) -> str:
    return code.replace("_", " ").title()


def _problem_response(*, status_code: int, code: str, detail: str) -> JSONResponse:
    body = ProblemDetail(
        type=code.lower(),
        title=_title_from_code(code),
        status=status_code,
        detail=detail,
        code=code,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(_: Request, exc: DomainError) -> JSONResponse:
        return _problem_response(status_code=_resolve_status(exc), code=exc.code, detail=exc.detail)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        return _problem_response(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="VALIDATION_ERROR",
            detail=detail or "Request validation failed.",
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "NOT_FOUND" if exc.status_code == status.HTTP_404_NOT_FOUND else "HTTP_ERROR"
        return _problem_response(status_code=exc.status_code, code=code, detail=str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error=str(exc))
        return _problem_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            detail="An unexpected error occurred.",
        )
